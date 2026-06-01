// content/jp-data.js — 日区随机地址 / 姓名 / 邮箱 / 密码 / 生日生成
// 数据来源：用户提供并验证过的日区 PayPal Auto Filler 脚本。
// 暴露到 window.JPData 供其他 content script 使用。

(function attachJPData(root) {
  const JP_ADDRESSES = [
    { street: 'Jinnan 1-19-11', city: 'Shibuya-ku', state: 'Tokyo', stateValues: ['TOKYO-TO', 'Tokyo', '東京都'], zip: '1500041' },
    { street: 'Nishi-Shinjuku 2-8-1', city: 'Shinjuku-ku', state: 'Tokyo', stateValues: ['TOKYO-TO', 'Tokyo', '東京都'], zip: '1638001' },
    { street: 'Marunouchi 1-9-1', city: 'Chiyoda-ku', state: 'Tokyo', stateValues: ['TOKYO-TO', 'Tokyo', '東京都'], zip: '1000005' },
    { street: 'Umeda 3-1-1', city: 'Osaka-shi Kita-ku', state: 'Osaka', stateValues: ['OSAKA-FU', 'Osaka', '大阪府'], zip: '5300001' },
    { street: 'Namba 5-1-60', city: 'Osaka-shi Chuo-ku', state: 'Osaka', stateValues: ['OSAKA-FU', 'Osaka', '大阪府'], zip: '5420076' },
    { street: 'Sakae 3-5-1', city: 'Nagoya-shi Naka-ku', state: 'Aichi', stateValues: ['AICHI-KEN', 'Aichi', '愛知県'], zip: '4600008' },
    { street: 'Meieki 1-1-4', city: 'Nagoya-shi Nakamura-ku', state: 'Aichi', stateValues: ['AICHI-KEN', 'Aichi', '愛知県'], zip: '4500002' },
    { street: 'Kita 2-jo Nishi 4-1', city: 'Sapporo-shi Chuo-ku', state: 'Hokkaido', stateValues: ['HOKKAIDO', 'Hokkaido', '北海道'], zip: '0600002' },
    { street: 'Kita 7-jo Nishi 4-3', city: 'Sapporo-shi Kita-ku', state: 'Hokkaido', stateValues: ['HOKKAIDO', 'Hokkaido', '北海道'], zip: '0600807' },
    { street: 'Ichibancho 3-7-1', city: 'Sendai-shi Aoba-ku', state: 'Miyagi', stateValues: ['MIYAGI-KEN', 'Miyagi', '宮城県'], zip: '9800811' },
    { street: 'Tenjin 2-11-1', city: 'Fukuoka-shi Chuo-ku', state: 'Fukuoka', stateValues: ['FUKUOKA-KEN', 'Fukuoka', '福岡県'], zip: '8100001' },
    { street: 'Hakataekimae 2-9-3', city: 'Fukuoka-shi Hakata-ku', state: 'Fukuoka', stateValues: ['FUKUOKA-KEN', 'Fukuoka', '福岡県'], zip: '8120011' },
    { street: 'Minatocho 1-1', city: 'Yokohama-shi Naka-ku', state: 'Kanagawa', stateValues: ['KANAGAWA-KEN', 'Kanagawa', '神奈川県'], zip: '2310017' },
    { street: 'Ekimae Honcho 26-1', city: 'Kawasaki-shi Kawasaki-ku', state: 'Kanagawa', stateValues: ['KANAGAWA-KEN', 'Kanagawa', '神奈川県'], zip: '2100007' },
    { street: 'Sannomiyacho 1-9-1', city: 'Kobe-shi Chuo-ku', state: 'Hyogo', stateValues: ['HYOGO-KEN', 'Hyogo', '兵庫県'], zip: '6500021' },
    { street: 'Kamiyacho 2-1-1', city: 'Hiroshima-shi Naka-ku', state: 'Hiroshima', stateValues: ['HIROSHIMA-KEN', 'Hiroshima', '広島県'], zip: '7300031' },
    { street: 'Nakajimacho 90', city: 'Kyoto-shi Nakagyo-ku', state: 'Kyoto', stateValues: ['KYOTO-FU', 'Kyoto', '京都府'], zip: '6048006' },
    { street: 'Shintoshin 11-1', city: 'Saitama-shi Chuo-ku', state: 'Saitama', stateValues: ['SAITAMA-KEN', 'Saitama', '埼玉県'], zip: '3300081' },
    { street: 'Fujimi 2-1-1', city: 'Chiba-shi Chuo-ku', state: 'Chiba', stateValues: ['CHIBA-KEN', 'Chiba', '千葉県'], zip: '2600015' },
    { street: 'Tenma 1-2-3', city: 'Shizuoka-shi Aoi-ku', state: 'Shizuoka', stateValues: ['SHIZUOKA-KEN', 'Shizuoka', '静岡県'], zip: '4200858' },
    { street: 'Omotecho 1-5-1', city: 'Okayama-shi Kita-ku', state: 'Okayama', stateValues: ['OKAYAMA-KEN', 'Okayama', '岡山県'], zip: '7000822' },
    { street: 'Shimotori 1-3-8', city: 'Kumamoto-shi Chuo-ku', state: 'Kumamoto', stateValues: ['KUMAMOTO-KEN', 'Kumamoto', '熊本県'], zip: '8600807' },
    { street: 'Kumoji 1-1-1', city: 'Naha-shi', state: 'Okinawa', stateValues: ['OKINAWA-KEN', 'Okinawa', '沖縄県'], zip: '9000015' },
    { street: 'Korinbo 1-1-1', city: 'Kanazawa-shi', state: 'Ishikawa', stateValues: ['ISHIKAWA-KEN', 'Ishikawa', '石川県'], zip: '9200961' },
  ];

  const JP_NAMES = [
    { kanaFirst: 'タロウ', kanaLast: 'サトウ', kanjiFirst: '太郎', kanjiLast: '佐藤' },
    { kanaFirst: 'ハナコ', kanaLast: 'スズキ', kanjiFirst: '花子', kanjiLast: '鈴木' },
    { kanaFirst: 'ケンタ', kanaLast: 'タカハシ', kanjiFirst: '健太', kanjiLast: '高橋' },
    { kanaFirst: 'ミサキ', kanaLast: 'タナカ', kanjiFirst: '美咲', kanjiLast: '田中' },
    { kanaFirst: 'ダイスケ', kanaLast: 'イトウ', kanjiFirst: '大輔', kanjiLast: '伊藤' },
    { kanaFirst: 'ユイ', kanaLast: 'ワタナベ', kanjiFirst: '結衣', kanjiLast: '渡辺' },
    { kanaFirst: 'ショウタ', kanaLast: 'ヤマモト', kanjiFirst: '翔太', kanjiLast: '山本' },
    { kanaFirst: 'アオイ', kanaLast: 'ナカムラ', kanjiFirst: '葵', kanjiLast: '中村' },
    { kanaFirst: 'ヒナ', kanaLast: 'コバヤシ', kanjiFirst: '陽菜', kanjiLast: '小林' },
    { kanaFirst: 'レン', kanaLast: 'カトウ', kanjiFirst: '蓮', kanjiLast: '加藤' },
    { kanaFirst: 'ソウタ', kanaLast: 'ヨシダ', kanjiFirst: '颯太', kanjiLast: '吉田' },
    { kanaFirst: 'メイ', kanaLast: 'ヤマダ', kanjiFirst: '芽衣', kanjiLast: '山田' },
    { kanaFirst: 'リク', kanaLast: 'ササキ', kanjiFirst: '陸', kanjiLast: '佐々木' },
    { kanaFirst: 'サクラ', kanaLast: 'ヤマグチ', kanjiFirst: '桜', kanjiLast: '山口' },
    { kanaFirst: 'ユウト', kanaLast: 'マツモト', kanjiFirst: '悠斗', kanjiLast: '松本' },
    { kanaFirst: 'リオ', kanaLast: 'イノウエ', kanjiFirst: '莉央', kanjiLast: '井上' },
    { kanaFirst: 'ハルト', kanaLast: 'キムラ', kanjiFirst: '陽翔', kanjiLast: '木村' },
    { kanaFirst: 'ナナ', kanaLast: 'ハヤシ', kanjiFirst: '七海', kanjiLast: '林' },
    { kanaFirst: 'ユウキ', kanaLast: 'サイトウ', kanjiFirst: '悠希', kanjiLast: '斎藤' },
    { kanaFirst: 'ミオ', kanaLast: 'シミズ', kanjiFirst: '美桜', kanjiLast: '清水' },
  ];

  const ALPHANUM = 'abcdefghijklmnopqrstuvwxyz0123456789';
  const PWD_ALPHABET = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^';

  function pick(arr) { return arr[Math.floor(Math.random() * arr.length)]; }

  root.JPData = {
    randomAddress() { return Object.assign({}, pick(JP_ADDRESSES)); },
    randomName() { return Object.assign({}, pick(JP_NAMES)); },
    randomEmail() {
      let s = '';
      for (let i = 0; i < 16; i++) s += ALPHANUM[Math.floor(Math.random() * ALPHANUM.length)];
      return s + '@gmail.com';
    },
    randomPassword() {
      let v = 'Aa1!';
      while (v.length < 14) v += PWD_ALPHABET[Math.floor(Math.random() * PWD_ALPHABET.length)];
      return v;
    },
    randomBirthdate() {
      const year = 1985 + Math.floor(Math.random() * 18);
      const month = String(1 + Math.floor(Math.random() * 12)).padStart(2, '0');
      const day = String(1 + Math.floor(Math.random() * 28)).padStart(2, '0');
      return `${year}/${month}/${day}`;
    },
  };
})(typeof window !== 'undefined' ? window : globalThis);
