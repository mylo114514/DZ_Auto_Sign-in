import yaml
import urllib.parse
import urllib.request
import requests
from bs4 import BeautifulSoup
import time
import json
from requests.exceptions import RequestException
import logging
import ssl


def load_config(filepath='config.yaml'):
    with open(filepath, 'r', encoding='utf-8') as file:
        config = yaml.safe_load(file)
    return config

config = load_config()

accounts = config['accounts']
ftqq_key = config.get('ftqq_SENDKEY')
Bark_key_url = config.get('Bark_BASE_URL')
Host = config.get('Host')

login_url = f"https://{Host}/member.php?mod=logging&action=login&loginsubmit=yes&infloat=yes&lssubmit=yes"
sign_in_page_url = f"https://{Host}/plugin.php?id=dc_signin:sign"
sign_in_url = f"https://{Host}/plugin.php?id=dc_signin:sign&inajax=1"

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.102 Safari/537.36',
    'Referer': sign_in_page_url,
    'Host': Host
}

# 日志配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 忽略 SSL 证书验证（用于修复 SSL 错误）
ssl._create_default_https_context = ssl._create_unverified_context


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
            time.sleep(2)
    logging.critical(f"多次请求失败，最终 URL: {url}")
    return None


def login(account):
    """
    登录论坛，检查登录是否成功
    :param account: 账号信息
    :return: 登录是否成功 (True/False)
    """
    try:
        # 登录表单数据
        login_data = {
            'username': account['username'],
            'password': account['password'],
            'loginsubmit': 'yes',
            'lssubmit': 'yes'
        }

        # 发送登录请求
        response = retry_request(login_url, method='POST', data=login_data)

        if response.status_code == 200:
            # logging.info(f"登录请求返回内容: {response.text}")

            # 检查返回的页面内容是否包含登录成功的标识
            if "欢迎您回来" in response.text or "登录成功" in response.text:
                logging.info(f"✔️账号 {account['username']} 登录成功")
                return True
            elif "请输入验证码后继续登录" in response.text:
                logging.error(f"❌账号 {account['username']} 登录失败，遇到验证码")
                return False
            elif "密码错误次数过多" in response.text:
                logging.error(f"❌账号 {account['username']} 被锁定，密码错误次数过多，请稍后再试")
                return False
            elif "密码错误" in response.text or "登录失败" in response.text:
                logging.error(f"❌账号 {account['username']} 登录失败，密码错误")
                return False
            else:
                logging.error(f"❌账号 {account['username']} 登录失败，未知错误")
                return False
        else:
            logging.error(f"登录请求失败，状态码: {response.status_code}")
            return False
    except Exception as e:
        logging.error(f"登录时发生错误: {str(e)}")
        return False


def get_sign_in_form_data():
    """
    获取签到页面的表单数据。
    :return: 表单数据或'已签到'字符串
    """
    try:
        response = retry_request(sign_in_page_url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')

            if "已签到" in response.text:
                logging.info("账号已经签到，无需再次签到")
                return "已签到"

            form = soup.find('form', {'id': 'signform'})
            if form:
                form_data = {input_tag['name']: input_tag.get('value', '') for input_tag in form.find_all('input') if 'name' in input_tag.attrs}
                form_data['emotid'] = '1'
                form_data['content'] = '记上一笔，hold住我的快乐！'
                logging.info(f"提取的表单数据: {form_data}")
                return form_data
            else:
                return "已签到"
        else:
            logging.error(f"获取签到页面失败，状态码: {response.status_code}")
            return None
    except Exception as e:
        logging.error(f"获取签到表单时发生错误: {str(e)}")
        return None


def sign_in(form_data):
    """
    提交签到请求
    :param form_data: 提取到的签到表单数据
    :return: 签到结果字符串
    """
    try:
        response = retry_request(sign_in_url, method='POST', data=form_data)
        if response.status_code == 200:
            if "签到成功" in response.text or "succeedhandle_signin" in response.text:
                return "签到成功"
            else:
                logging.warning("签到未成功，响应中未找到成功提示")
                return "签到失败"
        else:
            logging.error(f"签到请求失败，状态码: {response.status_code}")
            return "签到请求失败"
    except Exception as e:
        logging.error(f"提交签到请求时发生错误: {str(e)}")
        return "签到异常"


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

    text = "️🌏️签到结果汇总"
    desp = "\n".join(all_results[:2000])

    postdata = urllib.parse.urlencode({'text': text[:64], 'desp': desp}).encode('utf-8')
    url = f'https://sctapi.ftqq.com/{key}.send'

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=postdata, method='POST')
            with urllib.request.urlopen(req) as response:
                result = response.read().decode('utf-8')
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

    if not body:
        logging.error("⚠️Bark 推送内容 body 不能为空")
        return None

    url = f"{bark_base_url}{urllib.parse.quote(title)}/{urllib.parse.quote(body)}"

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
                logging.info("✈️Bark 推送成功")
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

    # 每次为新账户创建一个独立的 session
    global session
    session = requests.Session()

    # 先执行登录操作
    if not login(account):
        return f"❌️账号 {account['username']}: 登录失败，无法签到"

    # 获取签到表单数据
    form_data = get_sign_in_form_data()

    if form_data == "已签到":
        return f"🎯账号 {account['username']}: 已经签过到了！"

    if isinstance(form_data, dict):
        result = sign_in(form_data)
        return f"🎯账号 {account['username']}: {result}"

    return f"⚠️账号 {account['username']}: 获取签到表单失败"


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
    if ftqq_key:
        if ftqq_push(results, ftqq_key):
            logging.info("✈️所有账号的签到结果已通过Server酱推送。")
        else:
            logging.error("❌️Server酱消息推送失败。")
    else:
        logging.info("⚠️未检测到 Server酱 的 SENDKEY，跳过推送。")

    # Bark推送
    if Bark_key_url:
        bark_push(
            bark_base_url=Bark_key_url,
            title="🌏️签到结果汇总",
            body="\n".join(results),
            extra_params={"badge": 1, "level": "passive"} #Bark推送额外参数
        )
    else:
        logging.info("⚠️未检测到 Bark 的基础URL，跳过推送。")


if __name__ == '__main__':
    sign_in_for_all_accounts()
