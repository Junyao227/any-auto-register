"""日区 PayPal guest checkout 所需的随机地址 / 姓名数据。

数据来源：用户提供的 PayPal Auto Filler 脚本（日区版），保持字段语义一致：
- 地址：street / city / state / state_values（都道府县下拉候选）/ zip
- 姓名：kana_first/kana_last（假名）+ kanji_first/kanji_last（汉字）
"""

from __future__ import annotations

import random

# 日本随机地址池（都道府县下拉候选含大写英文 value / 英文 / 日文三种写法以提高匹配率）
JP_ADDRESSES = [
    {"street": "Jinnan 1-19-11", "city": "Shibuya-ku", "state": "Tokyo", "state_values": ["TOKYO-TO", "Tokyo", "東京都"], "zip": "1500041"},
    {"street": "Nishi-Shinjuku 2-8-1", "city": "Shinjuku-ku", "state": "Tokyo", "state_values": ["TOKYO-TO", "Tokyo", "東京都"], "zip": "1638001"},
    {"street": "Marunouchi 1-9-1", "city": "Chiyoda-ku", "state": "Tokyo", "state_values": ["TOKYO-TO", "Tokyo", "東京都"], "zip": "1000005"},
    {"street": "Umeda 3-1-1", "city": "Osaka-shi Kita-ku", "state": "Osaka", "state_values": ["OSAKA-FU", "Osaka", "大阪府"], "zip": "5300001"},
    {"street": "Namba 5-1-60", "city": "Osaka-shi Chuo-ku", "state": "Osaka", "state_values": ["OSAKA-FU", "Osaka", "大阪府"], "zip": "5420076"},
    {"street": "Sakae 3-5-1", "city": "Nagoya-shi Naka-ku", "state": "Aichi", "state_values": ["AICHI-KEN", "Aichi", "愛知県"], "zip": "4600008"},
    {"street": "Meieki 1-1-4", "city": "Nagoya-shi Nakamura-ku", "state": "Aichi", "state_values": ["AICHI-KEN", "Aichi", "愛知県"], "zip": "4500002"},
    {"street": "Kita 2-jo Nishi 4-1", "city": "Sapporo-shi Chuo-ku", "state": "Hokkaido", "state_values": ["HOKKAIDO", "Hokkaido", "北海道"], "zip": "0600002"},
    {"street": "Kita 7-jo Nishi 4-3", "city": "Sapporo-shi Kita-ku", "state": "Hokkaido", "state_values": ["HOKKAIDO", "Hokkaido", "北海道"], "zip": "0600807"},
    {"street": "Ichibancho 3-7-1", "city": "Sendai-shi Aoba-ku", "state": "Miyagi", "state_values": ["MIYAGI-KEN", "Miyagi", "宮城県"], "zip": "9800811"},
    {"street": "Tenjin 2-11-1", "city": "Fukuoka-shi Chuo-ku", "state": "Fukuoka", "state_values": ["FUKUOKA-KEN", "Fukuoka", "福岡県"], "zip": "8100001"},
    {"street": "Hakataekimae 2-9-3", "city": "Fukuoka-shi Hakata-ku", "state": "Fukuoka", "state_values": ["FUKUOKA-KEN", "Fukuoka", "福岡県"], "zip": "8120011"},
    {"street": "Minatocho 1-1", "city": "Yokohama-shi Naka-ku", "state": "Kanagawa", "state_values": ["KANAGAWA-KEN", "Kanagawa", "神奈川県"], "zip": "2310017"},
    {"street": "Ekimae Honcho 26-1", "city": "Kawasaki-shi Kawasaki-ku", "state": "Kanagawa", "state_values": ["KANAGAWA-KEN", "Kanagawa", "神奈川県"], "zip": "2100007"},
    {"street": "Sannomiyacho 1-9-1", "city": "Kobe-shi Chuo-ku", "state": "Hyogo", "state_values": ["HYOGO-KEN", "Hyogo", "兵庫県"], "zip": "6500021"},
    {"street": "Kamiyacho 2-1-1", "city": "Hiroshima-shi Naka-ku", "state": "Hiroshima", "state_values": ["HIROSHIMA-KEN", "Hiroshima", "広島県"], "zip": "7300031"},
    {"street": "Nakajimacho 90", "city": "Kyoto-shi Nakagyo-ku", "state": "Kyoto", "state_values": ["KYOTO-FU", "Kyoto", "京都府"], "zip": "6048006"},
    {"street": "Karasuma-dori Shiokoji-sagaru", "city": "Kyoto-shi Shimogyo-ku", "state": "Kyoto", "state_values": ["KYOTO-FU", "Kyoto", "京都府"], "zip": "6008216"},
    {"street": "Shintoshin 11-1", "city": "Saitama-shi Chuo-ku", "state": "Saitama", "state_values": ["SAITAMA-KEN", "Saitama", "埼玉県"], "zip": "3300081"},
    {"street": "Fujimi 2-1-1", "city": "Chiba-shi Chuo-ku", "state": "Chiba", "state_values": ["CHIBA-KEN", "Chiba", "千葉県"], "zip": "2600015"},
    {"street": "Tenma 1-2-3", "city": "Shizuoka-shi Aoi-ku", "state": "Shizuoka", "state_values": ["SHIZUOKA-KEN", "Shizuoka", "静岡県"], "zip": "4200858"},
    {"street": "Omotecho 1-5-1", "city": "Okayama-shi Kita-ku", "state": "Okayama", "state_values": ["OKAYAMA-KEN", "Okayama", "岡山県"], "zip": "7000822"},
    {"street": "Shimotori 1-3-8", "city": "Kumamoto-shi Chuo-ku", "state": "Kumamoto", "state_values": ["KUMAMOTO-KEN", "Kumamoto", "熊本県"], "zip": "8600807"},
    {"street": "Kumoji 1-1-1", "city": "Naha-shi", "state": "Okinawa", "state_values": ["OKINAWA-KEN", "Okinawa", "沖縄県"], "zip": "9000015"},
    {"street": "Korinbo 1-1-1", "city": "Kanazawa-shi", "state": "Ishikawa", "state_values": ["ISHIKAWA-KEN", "Ishikawa", "石川県"], "zip": "9200961"},
]

JP_NAMES = [
    {"kana_first": "タロウ", "kana_last": "サトウ", "kanji_first": "太郎", "kanji_last": "佐藤"},
    {"kana_first": "ハナコ", "kana_last": "スズキ", "kanji_first": "花子", "kanji_last": "鈴木"},
    {"kana_first": "ケンタ", "kana_last": "タカハシ", "kanji_first": "健太", "kanji_last": "高橋"},
    {"kana_first": "ミサキ", "kana_last": "タナカ", "kanji_first": "美咲", "kanji_last": "田中"},
    {"kana_first": "ダイスケ", "kana_last": "イトウ", "kanji_first": "大輔", "kanji_last": "伊藤"},
    {"kana_first": "ユイ", "kana_last": "ワタナベ", "kanji_first": "結衣", "kanji_last": "渡辺"},
    {"kana_first": "ショウタ", "kana_last": "ヤマモト", "kanji_first": "翔太", "kanji_last": "山本"},
    {"kana_first": "アオイ", "kana_last": "ナカムラ", "kanji_first": "葵", "kanji_last": "中村"},
    {"kana_first": "ヒナ", "kana_last": "コバヤシ", "kanji_first": "陽菜", "kanji_last": "小林"},
    {"kana_first": "レン", "kana_last": "カトウ", "kanji_first": "蓮", "kanji_last": "加藤"},
    {"kana_first": "ソウタ", "kana_last": "ヨシダ", "kanji_first": "颯太", "kanji_last": "吉田"},
    {"kana_first": "メイ", "kana_last": "ヤマダ", "kanji_first": "芽衣", "kanji_last": "山田"},
    {"kana_first": "リク", "kana_last": "ササキ", "kanji_first": "陸", "kanji_last": "佐々木"},
    {"kana_first": "サクラ", "kana_last": "ヤマグチ", "kanji_first": "桜", "kanji_last": "山口"},
    {"kana_first": "ユウト", "kana_last": "マツモト", "kanji_first": "悠斗", "kanji_last": "松本"},
    {"kana_first": "リオ", "kana_last": "イノウエ", "kanji_first": "莉央", "kanji_last": "井上"},
    {"kana_first": "ハルト", "kana_last": "キムラ", "kanji_first": "陽翔", "kanji_last": "木村"},
    {"kana_first": "ナナ", "kana_last": "ハヤシ", "kanji_first": "七海", "kanji_last": "林"},
    {"kana_first": "ユウキ", "kana_last": "サイトウ", "kanji_first": "悠希", "kanji_last": "斎藤"},
    {"kana_first": "ミオ", "kana_last": "シミズ", "kanji_first": "美桜", "kanji_last": "清水"},
]

_ALPHANUM = "abcdefghijklmnopqrstuvwxyz0123456789"
_PWD_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^"


def random_jp_address() -> dict:
    return dict(random.choice(JP_ADDRESSES))


def random_jp_name() -> dict:
    return dict(random.choice(JP_NAMES))


def random_email() -> str:
    return "".join(random.choice(_ALPHANUM) for _ in range(16)) + "@gmail.com"


def random_password() -> str:
    value = "Aa1!"
    while len(value) < 14:
        value += random.choice(_PWD_ALPHABET)
    return value


def random_birthdate() -> str:
    """生成 YYYY/MM/DD 格式生日（20-40 岁区间）。"""
    import datetime

    year = random.randint(datetime.date.today().year - 40, datetime.date.today().year - 20)
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    return f"{year}/{month:02d}/{day:02d}"
