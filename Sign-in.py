import os
import urllib.parse
import urllib.request
import requests
from bs4 import BeautifulSoup
import time
import json
from requests.exceptions import RequestException
import logging
import ssl

# 论坛域名
Host = ''
# Server酱密钥
ftqq_key = ''
# Bark密钥链接
Bark_key_url = ''

login_url = f"https://{Host}/member.php?mod=logging&action=login&loginsubmit=yes&infloat=yes&lssubmit=yes"
sign_in_page_url = f"https://{Host}/plugin.php?id=dc_signin:sign"
sign_in_url = f"https://{Host}/plugin.php?id=dc_signin:sign&inajax=1"

# 模拟浏览器的请求头
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.102 Safari/537.36',
    'Referer': sign_in_page_url,
    'Host': Host
}


# 配置多账号信息
accounts = [
    {'username': 'username1', 'password': 'password1'},
    {'username': 'username2', 'password': 'password2'}

]


SENDKEY = os.getenv('SENDKEY', ftqq_key)
BARK_BASE_URL = os.getenv('BARK_BASE_URL', Bark_key_url)

# 日志配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 忽略SSL证书验证
ssl._create_default_https_context = ssl._create_unverified_context

session = requests.Session()

def retry_request(url, method='GET', data=None, retries=3, timeout=10):
    """
    带重试机制的网络请求
    :param url: 请求URL
    :param method: 请求方式 (GET/POST)
    :param data: POST请求时发送的数据
    :param retries: 重试次数
    :param timeout: 超时时间
    :return: 请求响应对象
    """
    for attempt in range(retries):
        try:
            if method == 'POST':
                response = session.post(url, headers=headers, data=data, timeout=timeout)
            else:
                response = session.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response
        except RequestException as e:
            logging.error(f"请求失败: {e}, URL: {url}, 尝试次数({attempt + 1}/{retries})")
            time.sleep(2)  # 重试前等待
    logging.critical(f"多次请求失败，最终 URL: {url}")
    return None


def login(account):
    """
    执行账号登录
    :param account: 账号信息字典
    :return: 是否登录成功 (True/False)
    """
    payload = {
        'username': account['username'],
        'password': account['password'],
        'questionid': '0',
        'answer': ''
    }
    response = retry_request(login_url, method='POST', data=payload)
    if response:
        logging.info(f"✔️账号 {account['username']} 登录成功")
    return response and "欢迎您回来" in response.text


def get_sign_in_form_data():
    """
    获取签到页面表单数据
    :return: 包含formhash等表单数据的字典，或"已签到"提示
    """
    response = retry_request(sign_in_page_url)
    if response:
        soup = BeautifulSoup(response.text, 'html.parser')

        # 检查是否已经签到
        if "您今日已经签过到" in response.text:
            return "已签到"

        # 提取表单字段
        formhash = soup.find('input', {'name': 'formhash'})
        signsubmit = soup.find('input', {'name': 'signsubmit'})
        handlekey = soup.find('input', {'name': 'handlekey'})
        referer = soup.find('input', {'name': 'referer'})

        if formhash and signsubmit and handlekey and referer:
            return {
                'formhash': formhash['value'],
                'signsubmit': signsubmit['value'],
                'handlekey': handlekey['value'],
                'referer': referer['value']
            }
    return None


def sign_in(form_data):
    """
    执行签到
    :param form_data: 表单数据字典
    :return: 签到结果 (成功/失败/已签到)
    """
    emotid = '1'
    content = "记上一笔，hold住我的快乐！"

    sign_in_data = {
        'formhash': form_data['formhash'],
        'signsubmit': form_data['signsubmit'],
        'handlekey': form_data['handlekey'],
        'referer': form_data['referer'],
        'emotid': emotid,
        'content': content
    }

    response = retry_request(sign_in_url, method='POST', data=sign_in_data)
    if response:
        if "签到成功" in response.text:
            return "签到成功"
        elif "已经签过到" in response.text:
            return "已签到"
    return "签到失败"


def ftqq_push(all_results, key, retries=3):
    """
    通过Server酱推送消息
    :param all_results: 所有账号的签到结果字符串
    :param key: Server酱的SENDKEY
    :param retries: 发送失败后的重试次数
    """
    if not key:
        logging.info("⚠️未检测到 Server酱 的 SENDKEY，跳过推送。")
        return

    text = "🌏️签到结果汇总"
    desp = "\n".join(all_results[:2000])  # 限制内容长度避免超长

    postdata = urllib.parse.urlencode({'text': text[:64], 'desp': desp}).encode('utf-8')
    url = f'https://sctapi.ftqq.com/{key}.send'

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=postdata, method='POST')
            with urllib.request.urlopen(req) as response:
                result = response.read().decode('utf-8')

                # 修正推送成功的判断逻辑，基于 errno 和 error
                result_json = json.loads(result)
                if result_json.get('data', {}).get('errno') == 0 and result_json.get('data', {}).get('error') == "SUCCESS":
                    logging.info(f"✈️Server酱消息推送成功，响应: {result}")
                    return True  # 推送成功
                else:
                    logging.error(f"⚠️Server酱推送失败，响应内容: {result}")
        except Exception as e:
            logging.error(f"⚠️Server酱推送失败: {str(e)}")
        time.sleep(2)

    logging.critical("❌️多次尝试Server酱推送消息失败，请检查网络或配置。")
    return False


def bark_push(bark_base_url, title, body, extra_params=None):
    """
    通过 Bark 推送消息 (使用 URL 拼接方式)
    :param bark_base_url: 外部定义的完整基础URL
    :param title: 推送消息的标题
    :param body: 推送消息的正文
    :param extra_params: 额外的 GET 参数字典 (如: {"badge": 1, "sound": "minuet.caf"})
    :return: 返回请求的响应结果
    """
    if not bark_base_url:
        logging.info("⚠️未检测到 Bark 的基础URL，跳过推送。")
        return

    # 确保有 body 内容
    if not body:
        logging.error("⚠️Bark 推送内容 body 不能为空")
        return None

    # URL 拼接，包含 title 和 body
    url = f"{bark_base_url}{urllib.parse.quote(title)}/{urllib.parse.quote(body)}"

    # 处理额外参数，拼接为 GET 参数
    if extra_params:
        query_string = urllib.parse.urlencode(extra_params)
        url += f"?{query_string}"

    try:
        logging.info(f"🛫正在发送Bark的 GET 请求...")
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as response:
            result = response.read().decode('utf-8')
            result_json = json.loads(result)

            # 判断请求是否成功
            if result_json.get("code") == 200 and result_json.get("message") == "success":
                logging.info("✈️Bark 推送成功!")
            else:
                logging.error(f"❌️Bark 推送失败，响应: {result}")
            return result_json
    except Exception as e:
        logging.error(f"❌️Bark 推送失败: {str(e)}")
        return None


def sign_in_for_account(account):
    """
    为单个账号执行签到并返回签到结果
    :param account: 账号信息字典
    :return: 签到结果字符串
    """
    logging.info(f"📡正在为账号 {account['username']} 登录签到中...")
    if login(account):
        form_data = get_sign_in_form_data()
        if form_data == "已签到":
            return f"🎯账号 {account['username']}: 已经签过到了！"
        if isinstance(form_data, dict):
            result = sign_in(form_data)
            return f"🎯账号 {account['username']}: {result}"
        return f"⚠️账号 {account['username']}: 获取签到表单失败"
    return f"⚠️账号 {account['username']}: 登录失败"


def sign_in_for_all_accounts():
    """
    执行所有账号的签到，并在完成后统一推送消息
    """
    results = []  # 用于存储每个账号的签到结果
    for account in accounts:
        result = sign_in_for_account(account)
        results.append(result)
        logging.info(result)

    # Server酱推送
    if SENDKEY:
        if ftqq_push(results, SENDKEY):
            logging.info("✈️所有账号的签到结果已通过Server酱推送。")
        else:
            logging.error("❌️Server酱消息推送失败。")
    else:
        logging.info("⚠️未检测到 Server酱 的 SENDKEY，跳过推送。")

    # Bark推送
    if BARK_BASE_URL:
        bark_push(
            bark_base_url=BARK_BASE_URL,
            title="🌏️签到结果汇总",
            body="\n".join(results),
            extra_params={"badge": 1, "level": "passive"} #Bark推送额外参数
        )
    else:
        logging.info("❌️未检测到 Bark 的基础URL，跳过推送。")


if __name__ == '__main__':
    sign_in_for_all_accounts()