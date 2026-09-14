/* Demo state shown when the X-Genius service is not reachable (page opened without the backend).
   Clearly labelled in the UI; replaced by real data the moment the WebSocket connects. */
'use strict';

function demoAccount(i, username, group, status, color, extra = {}) {
  return Object.assign({
    index: i, username, group, proxy: `45.12.${i}.9:8080:user:pass`, has_token: true, has_password: i % 2 === 0,
    status, status_color: color, status_reason: '', groups_count: 60 + i * 7, last_launch: `12:0${i}:17`,
    is_active: true, is_mailing: false, is_paused: false, is_parsing: false, need_relogin: false, has_browser: true,
    running: false, messages_sent: 120 + i * 31, msg_24h: 40 + i, retweets: i * 3, comments_24h: i,
    followers: 1500 * i, has_messages: true, queue_len: 20 + i, disabled_groups: i % 3,
  }, extra);
}

const DEMO_STATE = {
  demo: true, phase: 'ready', version: 'demo', base_dir: 'D:\\SoftTwitter',
  summary: { all: 6, ready: 1, mailing: 2, paused: 1, error: 1, inactive: 2, messages: 1234, retweets: 56, comments: 7, groups: 412, browsers: 4 },
  groups: ['Alpha', 'Beta'],
  accounts: [
    demoAccount(1, 'crypto_ann', 'Alpha', 'MAILING', '#3498DB', { is_mailing: true, running: true }),
    demoAccount(2, 'max_trades', 'Alpha', 'ACTIVE', '#27ae60', { parked: true }),
    demoAccount(3, 'lena_nft', 'Beta', 'PAUSED', '#f39c12', { is_mailing: true, is_paused: true, running: true }),
    demoAccount(4, 'dm_bot_44', 'Beta', 'NEED RELOGIN', '#9b59b6', { need_relogin: true, is_active: false, status_reason: 'RELOGIN' }),
    demoAccount(5, 'old_acc', '', 'SUSPENDED', '#c0392b', { is_active: false, has_browser: false, status_reason: 'SUSPENDED', has_messages: false }),
    demoAccount(6, 'fresh_one', 'Alpha', 'Inactive', 'gray', { is_active: false, has_browser: false, has_token: false }),
  ],
};

const DEMO_LOGS = [
  '[12:01:17] @crypto_ann - Отправляем в https://x.com/i/chat/g2035650823573876754 (ждем 21.3с; в очереди 21)...',
  '[12:01:40] @crypto_ann - ✅ Отправка подтверждена (click).',
  '[12:02:05] @dm_bot_44 - ⚠️ Временная ошибка в https://x.com/i/chat/g1999 (retry 1). Группу НЕ удаляем — вернули в конец очереди.',
  '[12:02:30] @lena_nft - Paused mailing for lena_nft',
  '[12:03:01] @old_acc - Ошибка входа: SUSPENDED',
  '[12:03:10]  - Telegram bot: модуль TelegramBotManager отсутствует в сборке — бот не запущен.',
  '[12:03:20] @crypto_ann - ⏱ чат открыт за 6.2с, поле ввода через 3.1с (OK)',
  '[12:04:05] @crypto_ann - ⌨ Набрано: 212/212 порций за 44.8с (ср. 118 мс/клавишу, макс 2.3с)',
  '[12:04:10]  - [SYSMON] CPU 96% (ядер >90%: 29/32) · RAM 41/128 GB · Chrome 412 проц/14870 потоков = 74% CPU, 38.1 GB · Python 1%, потоков 140 · Selenium: в работе 41/128, вызовов 812, ср. 820 мс, макс 6.1 с · loop lag 12 мс · браузеров 50 (mailing 30, parsing 5)',
];

function enterDemo() {
  S.demo = true;
  applyState(DEMO_STATE);
  appendLogs(DEMO_LOGS);
  Load.demo();
  document.getElementById('demo-banner').classList.remove('hidden');
}

function leaveDemo() {
  S.demo = false;
  S.logs = [];
  rerenderLogs();
  Load.reset();
  document.getElementById('demo-banner').classList.add('hidden');
}
