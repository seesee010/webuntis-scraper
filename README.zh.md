# WebUntis Scraper

🇬🇧 [English](README.md) · 🇩🇪 [Deutsch](README.de.md) · 🇫🇷 [Français](README.fr.md) · 🇨🇳 [中文](README.zh.md)

> ⚠️ 本翻译由 AI（Anthropic Claude Opus 5.5）生成，可能有错误或不自然的表达。如有疑问，请以
> [英文版](README.md)为准。
>
> *This translation was made with AI and may be inaccurate. The English version is authoritative.*

基于 Playwright 的 WebUntis 抓取工具。它可以获取你的课表、考试、作业、缺勤记录和消息，并保存为
结构化的 JSON。

## 工作原理

JSON-RPC 接口前面有一个 WAF（网站防火墙），会拦截没有真实浏览器环境的请求。所以**所有操作**都通过
Playwright 完成：

1. **登录**：使用真实的登录表单（只有当 `sessions/storage_state.json` 中没有有效会话时才需要）。
2. **检查会话**：只有已登录的会话，`GET /WebUntis/api/token/new` 才会返回 JWT。它包含
   `person_id` 和角色。
3. **所有 API 请求**都通过 `page.evaluate(fetch(...))` 在浏览器中执行：
   - 课表：REST v1 `/api/rest/view/v1/timetable/entries`
     （需要把 JWT 作为 Bearer 令牌），备用方案是 JSON-RPC `getTimetable`
   - 考试：`/api/exams`
   - 作业：`/api/homeworks/lessons`
   - 缺勤：`/api/classreg/absences/students`
   - 消息：REST v1 `/api/rest/view/v1/messages`

`playwright-stealth` 会隐藏常见的机器人检测特征
（`navigator.webdriver`、`navigator.plugins`、`navigator.languages` 等）。

## 安装

Linux / macOS：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Windows（PowerShell）：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

## 安装为 `untis` 命令（Linux / macOS）

`bin/untis` 是一个小的启动脚本，它会用项目的 `.venv` 运行抓取工具。把它链接到 `PATH` 中的某个目录
（大多数 Linux 发行版的 `PATH` 都包含 `~/.local/bin`）：

```bash
ln -s "$PWD/bin/untis" ~/.local/bin/untis
untis -s --days-forward 0
```

## 配置

程序会在 `~/.config/untis/`（或 `$XDG_CONFIG_HOME/untis/`）中查找配置文件。会话、输出文件和调试截图
会保存到 `~/.local/share/untis/`，所以可以在任何目录下运行 `untis`。如果没有
`~/.config/untis/config.json`，所有文件都会使用项目文件夹（适合 Windows 或开发时使用）。

1. 创建配置目录并复制示例配置：

   ```bash
   mkdir -p ~/.config/untis
   cp config.example.json ~/.config/untis/config.json
   ```

   然后修改它：

   ```jsonc
   {
     "server": "nese",           // .webuntis.com 前面的子域名
     "school": "htbla_kaindorf", // ?school= 后面的值
     "username": "max.muster"
   }
   ```

   要找到 `server` 和 `school`，可以在 [webuntis.com](https://webuntis.com) 上搜索你的学校。
   跳转后的网址里包含这两个值，例如
   `https://nese.webuntis.com/WebUntis/?school=htbla_kaindorf`。

2. 把密码写入 `~/.config/untis/.env`：

   ```bash
   cp .env.example ~/.config/untis/.env
   chmod 600 ~/.config/untis/.env
   ```

   ```ini
   UNTIS_PASSWORD=你的密码
   ```

## 使用方法

```bash
# 默认运行（无界面，重复使用已保存的会话）
python -m src

# 忽略已保存的会话，重新登录
python -m src --form-login --no-headless --clear-session

# 其他时间范围
python -m src --days-back 7 --days-forward 30

# 日期快捷方式（代替 --days-back / --days-forward）
untis -s --today
untis -s --tomorrow        # 明天；如果明天没课，就是下一个上课日
untis -s --next            # 今天还有课就显示今天，否则显示下一个上课日
untis -s --week            # 本周（周一到周日）
untis -s --next-week
untis -s --date 12.10.     # 也可以写 12.10.2026 或 2026-10-12

# 同时保留 API 的原始数据
python -m src --keep-raw -v

# 在终端里显示简洁的每日视图（仍然会写入 JSON）
python -m src --short                   # 或 -s
python -m src -s --days-forward 0       # 只看今天
```

`--short` 为每个上课日显示一块内容：时间、科目、老师、教室，以及这节课发生了什么：

| 标记 | 含义 |
|---|---|
| `cancelled` | 这节课取消了 |
| `removed` | 这节课照常上，但你的班级被移出了这节课 |
| `no teacher` | 老师被移除了，暂时没有人代课 |
| `changed` | 其他变化，例如代课老师：`新老师 (for 原老师)` |
| `exam` | 考试 |
| `event` | 活动，例如外出参观（`★ 标题`，并显示负责的老师） |

被移除的老师会显示删除线（没有颜色时显示为 `~原老师~`）。每天的标题会显示当天实际开始和结束上课的
时间，例如 `Mon 05.10.  07:50–13:25`。

`--tomorrow` 和 `--next` 会查看真实的课表，所以会跳过周末、假期和所有课都取消的日子；这时当天的
标题会显示 `(next school day)`。

在每天的课表下面，会显示即将到来的考试、未完成的作业，以及一行缺勤和未读消息的统计。设置
`NO_COLOR=1` 可以关闭颜色。

输出保存在数据目录（`~/.local/share/untis/` 或项目文件夹）中的 `out/untis_<timestamp>.json` 和
`out/latest.json`。Cookie 保存在那里的 `sessions/storage_state.json` 中，这样以后运行时不需要
重新登录。

### 登录有问题？

如果用户名和密码正确，但登录还是失败（`Form login did not redirect away from the login page`），
请检查：

1. **服务器和学校标识正确吗？** 在 `webuntis.com` 上搜索你的学校；跳转后的网址是
   `https://<server>.webuntis.com/WebUntis/?school=<slug>`。
2. **密码里有特殊字符吗？** `.env` 支持 `=` 和引号，但开头的空格会被删除。
3. **有验证码 / SSO / 双重验证（2FA）吗？** → `python -m src --form-login --no-headless`
4. **截图：** 数据目录中的 `logs/login_failed.png` 显示了浏览器看到的页面。
5. **详细输出：** `python -m src -v`。

### 退出码

错误会以一行文字输出到 stderr（`untis: login failed: …`）；加上 `-v` 可以看到完整的错误追踪。

| 代码 | 含义 |
|---|---|
| `0` | 成功 |
| `1` | 意外错误（请报告） |
| `2` | 配置 / 安装问题（缺少配置，或没有安装 Chromium） |
| `3` | 登录失败 |
| `4` | 无法连接 WebUntis，或 WebUntis 返回了错误 |
| `130` | 用 Ctrl-C 中止 |

## 输出格式

```jsonc
{
  "meta": {
    "school": "...", "server": "...", "user": "...",
    "generated_at": "2026-06-02", "window": {"start": "...", "end": "..."}
  },
  "timetable": {
    "source": "rest_v1" | "jsonrpc",
    "start": "2026-06-02", "end": "2026-06-16",
    "own_classes": ["1AXYZ"],
    "days": [
      {"date": "2026-06-02", "entries": [
        {
          "start": "2026-06-02T08:00", "end": "2026-06-02T08:45",
          "status": "REGULAR" | "CHANGED" | "CANCELLED" | ...,
          "is_cancelled": false, "is_exam": false, "is_substitution": false,
          "is_event": false, "is_removed": false, "no_teacher": false,
          "lesson_text": "", "subjects": [{"short":"M","long":"Math"}],
          "teachers": [{"short":"NEW","long":"...","status":"ADDED","replaces":"OLD"}],
          "classes": [...], "rooms": [...]
        }
      ]}
    ],
    "lessons": [...]   // 使用 jsonrpc 备用方案时
  },
  "exams": {
    "source": "api" | "timetable_fallback",
    "exams": [ { "date": "2026-06-10", "start_time": "10:45", "name": "Test", ... } ]
  },
  "homework":  { "items": [...] },
  "absences":  { "items": [...] },
  "messages":  { "items": [...] }
}
```

## 说明

- **双重验证 / 验证码**：如果学校要求一次性验证码（OTP），先用 `--no-headless --clear-session`
  运行一次并输入验证码，之后就可以用无界面模式运行。
- **考试**：数据来自 `/api/exams`。如果这个接口不可用，会从课表中推断考试
  （`source: "timetable_fallback"`）。
- **请求频率限制**：最多每 300 毫秒发送一次请求。
- **原始数据**：不加 `--keep-raw` 时，所有 `raw` 字段都会被删除。
- **存储**：在项目文件夹中，`sessions/`、`out/`、`logs/`、`config.json` 和 `.env` 都已写入
  `.gitignore`。

## 项目结构

```
bin/
  untis             # 放到 PATH 中的启动脚本
src/
  __init__.py
  main.py           # 命令行入口
  config.py         # 读取 config.json 和 .env
  browser.py        # Playwright + stealth
  untis_client.py   # 登录、检查会话、在浏览器中调用 API
  normalize.py      # 原始数据 -> 整理后的字典
  scraper.py        # 流程控制
  exporter.py       # JSON 输出
  summary.py        # --short 每日视图
```
