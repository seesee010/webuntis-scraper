# WebUntis Scraper

🇬🇧 [English](README.md) · 🇩🇪 [Deutsch](README.de.md) · 🇫🇷 [Français](README.fr.md) · 🇨🇳 [中文](README.zh.md)

> ⚠️ 本翻译由 AI（Anthropic Claude Opus 5.5）生成，可能有错误或不自然的表达。如有疑问，请以
> [英文版](README.md)为准。
>
> *This translation was made with AI and may be inaccurate. The English version is authoritative.*

WebUntis 抓取工具（使用普通 HTTP，必要时用 Playwright 作为备用方案）。它可以获取你的课表、考试、作业、缺勤记录和消息，并保存为
结构化的 JSON。

## 工作原理

默认情况下（`--transport auto`）不需要浏览器：

1. **登录**：通过普通 HTTP 提交 WebUntis 的登录表单（`/WebUntis/j_spring_security_check`），
   只有当 `sessions/storage_state.json` 中保存的会话过期时才需要。WebUntis 会在一段时间不活动后
   结束会话（观察到大约 40 分钟），所以经常需要重新登录。
2. **检查会话**：只有已登录的会话，`GET /WebUntis/api/token/new` 才会返回 JWT。它包含
   `person_id` 和角色。
3. **API 请求**使用会话 Cookie（REST v1 还需要把 JWT 作为 Bearer 令牌）：
   - 课表：REST v1 `/api/rest/view/v1/timetable/entries`，
     备用方案是 JSON-RPC `getTimetable`
   - 考试：`/api/exams`
   - 作业：`/api/homeworks/lessons`
   - 缺勤：`/api/classreg/absences/students`
   - 消息：REST v1 `/api/rest/view/v1/messages`

如果 HTTP 登录收到意外的回应（例如被 WAF 拦截、需要双重验证或 SSO），`untis` 会改用真正的
**Chromium（通过 Playwright）**：它会填写登录表单，并在页面中执行 API 请求。用户名或密码错误时
*不会*再用浏览器重试（那只会多一次失败的登录）。两种方式使用同一个会话文件。

| `--transport` | 行为 |
|---|---|
| `auto`（默认） | 使用 HTTP，只有失败时才用浏览器 |
| `http` | 只用 HTTP，从不启动浏览器 |
| `browser` | 总是使用 Playwright（使用 `--no-headless` 时也是） |

在浏览器模式下，`playwright-stealth` 会隐藏常见的机器人检测特征
（`navigator.webdriver`、`navigator.plugins`、`navigator.languages` 等）。

## 安装

### 使用 pipx（推荐）

[pipx](https://pipx.pypa.io) 会把 `untis` 安装为命令，并放在独立的隔离环境中，不会和其他 Python 包冲突。

**1. 安装 pipx**（只需一次）：

```bash
sudo pacman -S python-pipx            # Arch / Omarchy
sudo apt install pipx                 # Debian / Ubuntu
brew install pipx                     # macOS
python -m pip install --user pipx     # 其他系统，包括 Windows

pipx ensurepath                       # 把 ~/.local/bin 加入 PATH（之后请打开新的终端）
```

> 这里只测试了 Arch / Omarchy 的命令。Debian / Ubuntu、macOS 和 Windows 的命令（以及下面 Windows 上
> Chromium 的路径）来自 [pipx 官方文档](https://pipx.pypa.io/latest/how-to/install-pipx.html)，没有在这里测试过。

**2. 安装 `untis`：**

```bash
pipx install git+https://github.com/seesee010/webuntis-scraper
untis --version
```

**3. 配置**学校和登录信息，参见[配置](#配置)。然后：

```bash
untis -s --today
```

**可选：Chromium。** `untis` 通过普通 HTTP 与 WebUntis 通信，只有备用方案（`--transport browser`、双重验证/SSO）才需要浏览器。启用方法如下（在 Windows 上，路径以 `\webuntis-scraper\Scripts\playwright.exe` 结尾）：

```bash
"$(pipx environment --value PIPX_LOCAL_VENVS)/webuntis-scraper/bin/playwright" install chromium
```

**更新 / 卸载：**

```bash
pipx reinstall webuntis-scraper       # 从 GitHub 获取最新版本
pipx uninstall webuntis-scraper
```

`pipx upgrade` 不会更新从 GitHub 安装的版本（它只检查软件包索引），所以请使用 `pipx reinstall`。

如果你也要修改代码，请改用下面的安装方式。两者都会使用 `~/.local/bin/untis`，所以不要同时安装。

### 从源码目录安装（开发）

Linux / macOS:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
pytest                     # 运行测试
```

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
playwright install chromium
```

`bin/untis` 会用源码目录中的 `.venv` 运行程序，不需要安装。把它链接到 `PATH` 中的某个目录
（大多数 Linux 发行版的 `PATH` 都包含 `~/.local/bin`）：

```bash
ln -s "$PWD/bin/untis" ~/.local/bin/untis
untis -s --today
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

3. **可选：默认参数。** 总是想用的选项可以写进 `config.json`：

   ```jsonc
   {
     "default_args": ["--short"]
   }
   ```

   ```bash
   untis                                  # = untis --short
   untis --no-short                       # 本次运行关闭默认选项
   UNTIS_DEFAULT_ARGS="-s --today" untis   # 通过环境变量设置
   ```

   显式给出的选项优先：`untis --transport browser` 会替换默认的 `--transport http`；显式的时间范围（`--week`、`--from`、`--days-forward` 等）会替换默认的时间范围，而不会产生冲突。开关选项可以用 `--no-short`、`--no-keep-raw`、`--no-calendar-days` 或 `--no-verbose` 在单次运行中关闭。`UNTIS_DEFAULT_ARGS` 的作用相同，并且优先于配置文件；`--config`、`--env`、`--help` 和 `--version` 不能作为默认参数。`untis -v` 会显示实际使用的参数。

## 使用方法

```bash
# 默认运行（无界面，重复使用已保存的会话）
untis

# 忽略已保存的会话，重新登录
untis --form-login --no-headless --clear-session

# 其他时间范围：今天加上接下来的 4 个上课日
# （周末、假期和所有课都取消的日子不计算在内）
untis -s --days-forward 4
untis -s --days-back 2 --days-forward 0    # 最近 2 个上课日 + 今天
untis -s --days-forward 4 --calendar-days  # 改为按日历天数计算

# 日期快捷方式（代替 --days-back / --days-forward）
untis -s --today
untis -s --tomorrow        # 明天；如果明天没课，就是下一个上课日
untis -s --next            # 今天还有课就显示今天，否则显示下一个上课日
untis -s --week            # 本周（周一到周日）
untis -s --next-week
untis -s --date 12.10.     # 也可以写 12.10.2026 或 2026-10-12
untis -s --from mon --to fri     # 本周的上课日
untis -s --from tue --to mon     # 本周二到下周一
untis -s --to fri                # 从今天到周五
untis -s --offline               # 使用上次获取的数据，不联网
untis -s --max-age 10m           # 缓存不超过 10 分钟就使用，否则重新获取

# 同时保留 API 的原始数据
untis --keep-raw -v

# 在终端里显示简洁的每日视图（仍然会写入 JSON）
untis --short                   # 或 -s
untis -s --days-forward 0       # 只看今天
untis --oneline --week          # 每天一行
untis --table --week            # 周课表：日期为列，课时为行
```

`--from` / `--to` 支持 `--date` 的所有格式，另外还支持 `today`、`tomorrow` 以及英文或德文的星期名称（`mon`、`monday`、`mo`、`montag` 等）。星期名称指本周的那一天；如果这样 `--to` 会早于 `--from`，则指下周的那一天。

每次真正运行都会把数据保存到 `~/.local/share/untis/cache/last.json`（私有，不含 `raw`）。`--offline` 只使用这里的数据，从不联网；如果缓存不包含所请求的日期（或来自其他账户），会给出提示并以代码 4 退出。`--max-age` 在缓存足够新且包含所请求的范围时使用缓存，否则重新获取。来自缓存的结果会在标题中显示数据的年龄，例如 `(cached, 14 min old)`，并且不会写入新的 JSON 文件。

`--short` 为每个上课日显示一块内容：时间、科目、老师、教室，以及这节课发生了什么：

| 标记 | 颜色 | 含义 |
|---|---|---|
| `cancelled` | 红色，删除线 | 这节课取消了 |
| `removed` | 灰色，删除线 | 这节课照常上，但你的班级被移出了这节课 |
| `no teacher` | 黄色 | 老师被移除了，暂时没有人代课 |
| `changed` | 绿色；代课老师 / 新教室为粗体绿色 | 其他变化，例如代课老师：`新老师 (for 原老师)` |
| `exam` | 粗体洋红 | 考试 |
| `event` | 粗体蓝色 | 活动，例如外出参观（`★ 标题`，并显示负责的老师） |

被移除的老师会显示删除线（没有颜色时显示为 `~原老师~`）。每天的标题会显示当天实际开始和结束上课的
时间，例如 `Mon 05.10.  07:50–13:25`。

对于今天，每日视图还会显示你现在所处的位置：正在上的课会带有 `▶` 和剩余时间，已经结束的课会变暗；
在课间或上课前，会有一条 “now” 线显示下一节课什么时候开始。被取消的课不会被标记为当前课程，放学后不会
标记任何内容。

```
  07:50–09:35  MATH  TCH1  R101                       (dimmed: already over)
▶ 09:40–10:30  GER   TCH2  R101   now · 18 min left
  10:45–11:35  PROG  TCH3  R101

  ──── now 10:37 · next in 8 min ────                 (in a break)
```

`--tomorrow` 和 `--next` 会查看真实的课表，所以会跳过周末、假期和所有课都取消的日子；这时当天的
标题会显示 `(next school day)`。

在每天的课表下面，会显示即将到来的考试、未完成的作业，以及一行缺勤和未读消息的统计。设置
只有在终端中才会显示颜色；`--color always` 强制显示颜色（例如用于 `less -R`），`--color never` 或 `NO_COLOR=1` 会关闭颜色。`untis --legend` 会显示每种颜色和标记的含义。

另外还有两种紧凑的显示方式。`--oneline` 每天显示一行，按学校的课时表每节课一个条目（连堂课出现两次，空闲课时显示为 `-`，并行的小组显示为 `NET/PROG`）。`--table` 显示一个表格，日期为列、课时为行，每周一个表格，宽度适应终端，后面和 `-s` 一样显示考试和作业。两种方式使用相同的颜色；没有颜色时，`*` 表示有变化，`~X~` 表示课程取消或被移出，`!` 表示考试。

```
Mon 05.10.  07:50–13:25  MATH MATH GER - ENG* PROG
Tue 06.10.  07:50–13:25  NET/PROG NET/PROG ~GEO~ MATH! SOC GEO
```

输出保存在数据目录（`~/.local/share/untis/` 或项目文件夹）中的 `out/untis_<timestamp>.json` 和
`out/latest.json`。Cookie 保存在那里的 `sessions/storage_state.json` 中，这样以后运行时不需要
重新登录。

### 登录有问题？

如果用户名和密码正确，但登录还是失败（`Form login did not redirect away from the login page`），
请检查：

1. **服务器和学校标识正确吗？** 在 `webuntis.com` 上搜索你的学校；跳转后的网址是
   `https://<server>.webuntis.com/WebUntis/?school=<slug>`。
2. **密码里有特殊字符吗？** `.env` 支持 `=` 和引号，但开头的空格会被删除。
3. **有验证码 / SSO / 双重验证（2FA）吗？** → `untis --transport browser --no-headless --form-login`
4. **截图：** 数据目录中的 `logs/login_failed.png` 显示了浏览器看到的页面。
5. **详细输出：** `untis -v`。

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

## 安全

`untis` 会保存个人数据，因此只允许你的用户账户读取这些数据：

- **密码：** `~/.config/untis/.env`。请设置为只有你能读取（`chmod 600`）。如果其他用户可以读取，`untis` 会发出警告。
- **登录会话：** 任何拿到 `~/.local/share/untis/sessions/storage_state.json` 的人，都可以在会话过期前冒充你。该文件以 `600` 权限创建，所在目录为 `700`。
- **输出和调试文件：** `out/`、`cache/`（你的姓名、课表、缺勤记录）和 `logs/`（WebUntis 页面截图）同样是私有的，旧版本留下的文件会在下次运行时自动修正。分享截图前请先检查。
- **浏览器沙箱：** Chromium 默认启用沙箱。只有在 Docker 等需要的环境中，才在 `config.json` 中设置 `"browser_no_sandbox": true`（以 root 运行时会自动启用）。

```bash
chmod 600 ~/.config/untis/.env                            # 只有你能读取密码
untis --clear-session                                     # 退出登录：删除保存的会话
rm ~/.local/share/untis/sessions/storage_state.json       # 手动执行同样的操作
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
pyproject.toml      # 包信息、依赖、`untis` 命令
bin/
  untis             # 源码目录的启动脚本
src/untis/
  __init__.py       # 版本
  __main__.py       # python -m untis
  main.py           # 命令行入口
  config.py         # 读取 config.json 和 .env
  browser.py        # Playwright + stealth
  http_transport.py # 通过普通 HTTP 登录和发送请求（默认）
  untis_client.py   # 登录（HTTP 或浏览器）、检查会话、调用 API
  normalize.py      # 原始数据 -> 整理后的字典
  scraper.py        # 流程控制
  exporter.py       # JSON 输出
  summary.py        # --short 每日视图
```
