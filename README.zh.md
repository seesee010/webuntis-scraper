# WebUntis Scraper

![Made With:vibecoding](https://img.shields.io/badge/made%20with-vibecoding-blueviolet?style=plastic)
![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![pipx](https://img.shields.io/badge/install-pipx-2A6DB2)
![Platforms](https://img.shields.io/badge/platform-linux%20%7C%20macos%20%7C%20windows-informational)

🇬🇧 [English](README.md) · 🇩🇪 [Deutsch](README.de.md) · 🇫🇷 [Français](README.fr.md) · 🇨🇳 [中文](README.zh.md)

> ⚠️ 本翻译由 AI（Anthropic Claude Opus 5.5）生成，可能有错误或不自然的表达。如有疑问，请以
> [英文版](README.md)为准。
>
> *This translation was made with AI and may be inaccurate. The English version is authoritative.*

<!--
  TODO：在这里放一个循环播放 `untis --short --next` 的演示 gif。
  <p align="center"><img src="docs/demo.gif" alt="untis --short --next" width="640"></p>
-->

`untis` 是一个命令行工具，可以把**你的** WebUntis 课表、考试、作业、缺勤记录和消息直接带到
终端里（也可以保存为结构化的 JSON）。不需要打开浏览器标签页，不需要安装 App，不需要点来点
去——只要敲一下 `untis`，就能看到今天的课是怎样的。

## 快速开始

```bash
pipx install git+https://github.com/seesee010/webuntis-scraper
untis init          # 问几个问题，测试登录，保存配置
untis --short --next
```

就这么简单。`untis init` 是推荐的设置方式——它会询问你学校的 WebUntis 网址、用户名和密码，
帮你测试登录，并写好配置文件，完全不需要手动编辑 JSON。详见下面的[安装](#安装)和[配置](#配置)。

## 你会得到什么

- 你的**课表**，取消的课、代课/换教室和考试都会高亮显示
- 在终端里直接看的紧凑**每日视图、单行视图或周课表**，带颜色
- 即将到来的**考试**和**作业**（含截止日期，成绩出来后也会显示）
- **缺勤记录**（含汇总：天数、缺课节数、未请假数）和未读**消息**
- `--now` 用来回答“我现在在上什么课”，还自带一个 [Waybar](https://github.com/Alexays/Waybar) 模块
- `--changes --notify`，一旦有变化（代课、取消、新作业……）就发桌面通知
- `--live` 让任意视图保持打开，并每隔几分钟自动刷新
- 每次运行都有结构化的 **JSON** 输出，方便接到别的地方处理

<details>
<summary><strong>工作原理（技术细节）</strong></summary>

默认情况下（`--transport auto`）不需要浏览器：

1. **登录**：通过普通 HTTP 提交 WebUntis 的登录表单（`/WebUntis/j_spring_security_check`），
   只有当 `sessions/storage_state.json` 中保存的会话过期时才需要。WebUntis 会在 15 分钟不活动后
   结束会话，所以经常需要重新登录。
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

</details>

## 安装

### 使用 pipx（推荐）

[pipx](https://pipx.pypa.io) 会把 `untis` 安装为命令，并放在独立的隔离环境中，不会和其他 Python 包冲突。这是安装 `untis` 的推荐方式——下面的源码安装方式只适合想修改代码本身的人。

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

**3. 设置账户**：运行 `untis init`（推荐方式——手动设置方法见[配置](#配置)）：

```bash
untis init
```

**4. 运行：**

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

<details>
<summary><strong>从源码目录安装（给贡献者）</strong></summary>

如果你想修改代码本身，请用这种方式代替 pipx。两者都会使用 `~/.local/bin/untis`，所以不要同时安装。

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

`pip install -e` 还会创建命令 `.venv/bin/untis`，它总是运行这个源码目录中的代码。把它链接到 `PATH`
中的某个目录（大多数 Linux 发行版的 `PATH` 都包含 `~/.local/bin`）：

```bash
ln -s "$PWD/.venv/bin/untis" ~/.local/bin/untis
untis -s --today
```

</details>

## 配置

**`untis init` 是推荐的设置方式**——它会询问你学校的任意一个 WebUntis 网址（登录页面，或新界面
的任意页面，例如 `…/today`；这时会通过 WebUntis 公开的学校搜索找到学校）、用户名和密码，测试
登录，然后写入 `config.json` 和 `.env`（权限 `600`）。已有的文件会被更新而不是替换，密码永远
不会显示。如果账户使用双重验证或 SSO，请加上 `--no-verify`。

```bash
untis init                                         # 交互式：学校网址、用户名、密码、登录测试
untis init --search "School name"                  # 改为按学校名称搜索
untis init --url URL --username NAME < password    # 用于脚本（密码从 stdin 读取）
```

程序会在 `~/.config/untis/`（或 `$XDG_CONFIG_HOME/untis/`）中查找配置文件。会话、输出文件和调试截图
会保存到 `~/.local/share/untis/`，所以可以在任何目录下运行 `untis`。如果没有
`~/.config/untis/config.json`，所有文件都会使用项目文件夹（适合 Windows 或开发时使用）。

<details>
<summary><strong>改为手动配置</strong></summary>

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

</details>

## 使用方法

日常会用到的命令：

```bash
untis                      # 默认运行（无界面，重复使用已保存的会话）
untis -s --today           # 今天的紧凑视图
untis -s --next            # 下一个有课的上课日的紧凑视图
untis -s --week            # 本周上课日（周一到周五，等同于 --from mon --to fri）
untis --now                # 当前的课和下一节课
untis --tests               # 所有即将到来的考试
untis --homework             # 所有未完成的作业
untis --absences             # 本学年的缺勤记录，带汇总
untis --changes --notify   # 自上次以来的变化，作为桌面通知
```

`--short`（或 `-s`）为每个上课日显示一块内容：时间、科目、老师、教室，以及这节课发生了什么
（取消、代课、考试、活动……），在终端里带颜色显示。对于今天，视图还会显示你现在所处的位置——
正在上的课会带有 `▶` 和剩余时间：

```
  07:50–09:35  MATH  TCH1  R101                       (dimmed: already over)
▶ 09:40–10:30  GER   TCH2  R101   now · 18 min left
  10:45–11:35  PROG  TCH3  R101

  ──── now 10:37 · next in 8 min ────                 (in a break)
```

`untis --legend` 会显示每种颜色和标记的含义。

<details>
<summary><strong>完整命令参考</strong></summary>

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
untis -s --week            # 本周上课日（周一到周五，等同于 --from mon --to fri）
untis -s --next-week
untis -s --date 12.10.     # 也可以写 12.10.2026 或 2026-10-12
untis -s --from mon --to fri     # 本周的上课日
untis -s --from tue --to mon     # 本周二到下周一
untis -s --to fri                # 从今天到周五
untis -s --offline               # 使用上次获取的数据，不联网
untis -s --max-age 10m           # 缓存不超过 10 分钟就使用，否则重新获取

# 同时保留 API 的原始数据
untis --keep-raw -v

# JSON 输出
untis -s --no-json               # 只显示终端视图，不在 out/ 中写入文件
untis --json - --days-forward 0 | jq '.timetable.days[0].entries[].subjects'
untis --keep 5                   # 只保留最新的 5 个带时间戳的文件

# 在终端里显示简洁的每日视图（仍然会写入 JSON，除非使用 --no-json）
untis --short                   # 或 -s
untis -s --days-forward 0       # 只看今天
untis --oneline --week          # 每天一行
untis --table --week            # 周课表：日期为列，课时为行
untis --start tomorrow           # 明天第一节真正上的课，例如 07:50
untis --end                      # 今天什么时候放学
untis --free next                # 下一个上课日的空闲课时
untis --start tomorrow || echo "sleep in"   # 退出码 5 = 那天没有课
untis --tests                    # 到学年结束前所有即将到来的考试
untis -t --days-back 30 --days-forward 0   # 最近 30 个上课日的考试（含成绩）
untis --homework                 # 本学年的所有作业
untis -H --days-forward 5        # 接下来 5 个上课日内到期的作业
untis -t -H                      # 两个部分都显示
untis --absences                 # 本学年的缺勤记录，带汇总
untis -A --days-back 10 --days-forward 0   # 最近 10 个上课日的缺勤记录
untis --now                      # 当前的课和下一节课
untis --now --format waybar      # 用于 Waybar 自定义模块的 JSON
untis --changes                  # 自上次 --changes 运行以来的变化
untis --changes --notify         # ……并作为桌面通知发送
untis --live                     # 保持 -s 视图打开，每 5 分钟重绘一次
untis --now --live 1m --max-age 10m   # 当前课程，每分钟从缓存刷新
```

`--from` / `--to` 支持 `--date` 的所有格式，另外还支持 `today`、`tomorrow` 以及英文或德文的星期名称（`mon`、`monday`、`mo`、`montag` 等）。星期名称指本周的那一天；如果这样 `--to` 会早于 `--from`，则指下周的那一天。

每次真正运行都会把数据保存到 `~/.local/share/untis/cache/last.json`（私有，不含 `raw`）。`--offline` 只使用这里的数据，从不联网；如果缓存不包含所请求的日期（或来自其他账户），会给出提示并以代码 4 退出。`--max-age` 在缓存足够新且包含所请求的范围时使用缓存，否则重新获取。来自缓存的结果会在标题中显示数据的年龄，例如 `(cached, 14 min old)`，并且不会写入新的 JSON 文件。

### `--short` 标记

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

`--tomorrow` 和 `--next` 会查看真实的课表，所以会跳过周末、假期和所有课都取消的日子；这时当天的
标题会显示 `(next school day)`。

在每天的课表下面，会显示即将到来的考试、未完成的作业，以及一行缺勤和未读消息的统计。
只有在终端中才会显示颜色；`--color always` 强制显示颜色（例如用于 `less -R`），`--color never` 或 `NO_COLOR=1` 会关闭颜色。

另外还有两种紧凑的显示方式。`--oneline` 每天显示一行，按学校的课时表每节课一个条目（连堂课出现两次，空闲课时显示为 `-`，并行的小组显示为 `NET/PROG`）。`--table` 显示一个带边框的表格，每天一列、每节课一行（开始和结束时间），每周一个表格，宽度适应终端，后面和 `-s` 一样显示考试和作业。连续相同的课（连堂课，或同一教室的同一科目）合并为一个单元格；某天最后一节课之后，该列完全留空（不再画空格子，也没有线条）。每个单元格整体着色：取消为红色，考试为品红色，变化为绿色，你缺勤的课为灰色。上课期间，今天这一列会像按天视图一样显示当前进度：正在上的课带有 `▶`，已经结束的课时变暗，表格下方的一行显示现在在上什么课、还剩多久（`▶ now 09:52 · MATH · 38 min left`），或者下一节是什么。两种方式使用相同的颜色；没有颜色时，`*` 表示有变化，`~X~` 表示课程取消或被移出，`!` 表示考试，表格中的 `[X]` 表示你缺勤的课。

```
Mon 05.10.  07:50–13:25  MATH MATH GER - ENG* PROG
Tue 06.10.  07:50–13:25  NET/PROG NET/PROG ~GEO~ MATH! SOC GEO
```

```
$ untis --table --from mon --to tue
┌───────┬────────────┬────────────┐
│ Time  │ Mon 05.10. │ Tue 06.10. │
├───────┼────────────┼────────────┤
│ 07:50 │ MATH       │ NET/PROG   │
│ 08:40 │ R101       │ R201, R202 │
├───────┤            ├────────────┤
│ 08:45 │            │ ~GEO~      │
│ 09:35 │            │ R101       │
├───────┼────────────┼────────────┤
│ 09:40 │            │ [MATH!]    │
│ 10:30 │            │ R101       │
├───────┼────────────┼────────────┘
│ 10:45 │ ENG*       │
│ 11:35 │ R101       │
└───────┴────────────┘
```

`--start`、`--end` 和 `--free` 回答关于某一天的一个问题，只输出答案：`today`（默认）、`tomorrow`、`next`（下一个上课日）、日期或星期名称（下一个该星期日）。取消的课和你的班级被移出的课不计算在内，所以第一节课取消时 `--start` 会往后推。空闲课时来自学校的课时表。如果那天没有课，会输出 `-` 并以代码 5 退出。`--format json` 会输出 `{"date", "start", "end", "first", "free"}`。只会获取课表，不会写入 JSON 文件。

`--tests`（也可以用 `-t` / `--exams`）只显示考试和测验，按日期排序并显示 “in N days”，如果 WebUntis 提供成绩则显示成绩，已经过去的考试会变暗。不指定时间范围时，范围是从今天到学年结束（配置中的 `days_forward` 在这里不适用）；使用 `--days-forward`、`--from`、`--week` 等时只显示该范围。只会获取考试数据。

`--homework`（也可以用 `-H`）只显示作业：未完成的按截止日期排在前面（已逾期的为红色），然后是已完成的（变暗并带 ✓），每条作业都会显示完整内容并按终端宽度换行，如有备注和附件也会显示。不指定时间范围时包含整个学年；使用 `--days-forward`、`--from` 等时，只显示在该范围内*到期*的作业（WebUntis 按布置作业的那节课筛选，所以 `untis` 会往前多查一段时间，再自己按截止日期筛选）。与 `--tests` 一起使用时会显示两个部分。

`--absences`（也可以用 `-A`）只显示缺勤记录，最早的在前，标题行显示汇总：天数、缺课节数以及有多少条未获准假。每条缺勤记录显示时间、涉及的课节数、是否已准假（或学校自己的请假状态）、原因，以及缩进显示的说明和请假备注；未准假的显示为红色。课节数按学校的作息时间表计算：与缺勤时间有重叠的每一节课都算。跨多天的缺勤只计算其中的工作日（中间的假期无法得知，也会计算在内）。不指定时间范围时包含整个学年；使用 `--days-back`、`--from` 等时只包含该范围。可以与 `--tests` 和 `--homework` 组合使用。

`--now` 显示正在上的课（及剩余时间）和下一节课；放学后或周末则显示下一个上课日的第一节课。`--format json` 以数据形式输出同样的内容，`--format waybar` 输出 [Waybar](https://github.com/Alexays/Waybar) 自定义模块所需的 JSON（`text`、`tooltip`、`class`，其中 `class` 是该节课的状态或 `idle`）。`--idle-empty` 在课间不输出任何内容，这样模块会自动隐藏。配合 `--max-age`，状态栏会使用缓存数据，而不是每分钟都请求 WebUntis：

```jsonc
// ~/.config/waybar/config.jsonc
"custom/untis": {
  "exec": "untis --now --format waybar --max-age 10m --idle-empty",
  "return-type": "json",
  "interval": 60
}
```

`--changes` 会把课表、考试和作业与上一次 `--changes` 运行时保存的状态（私有地保存在 `~/.local/share/untis/state/`）进行比较，只输出变化：取消的课、代课、换教室、你的班级被移出或消失的课、新增或删除的考试、新作业。只比较两个时间范围都包含的日期。第一次运行只会保存状态。退出码 `10` 表示有变化，`0` 表示没有变化。`--notify` 还会把每条变化作为桌面通知发送（Linux 上用 `notify-send`，macOS 上用 `osascript`）。`contrib/systemd/` 中有一个用户定时器，在上课日每 15 分钟执行一次：

```bash
cp contrib/systemd/untis-changes.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now untis-changes.timer
```

`--live [INTERVAL]` 让 `untis` 持续运行，每隔 INTERVAL 重绘一次输出（默认 `5m`，至少 `60s`；格式与 `--max-age` 相同），直到按下 Ctrl-C。它适用于所有视图：`-s`（未选择视图时的默认值）、`--oneline`、`--table`、`--tests`、`--homework`、`--now` 以及 `--start`/`--end`/`--free`。底部一行显示上次更新时间和下次刷新时间。如果某次刷新失败（例如没有网络），上一次的输出会保留，错误显示在下方；配置错误和登录错误会结束循环。使用 `--format json`/`waybar` 时，每次刷新改为输出一行，没有 `interval` 的 Waybar 模块可以持续读取。与 `--max-age` 一起使用时，只有缓存过旧才会访问 WebUntis。`--live` 不能与 `--changes` 组合（请使用 systemd 定时器），也不能放进 `default_args`。

输出保存在数据目录（`~/.local/share/untis/` 或项目文件夹）中的 `out/untis_<timestamp>.json` 和
`out/latest.json`。Cookie 保存在那里的 `sessions/storage_state.json` 中，这样以后运行时不需要
重新登录。

默认只保留最新的 20 个带时间戳的文件：可以用 `--keep N` 或 `config.json` 中的 `"keep_json": N` 修改，`0` 只写入 `latest.json`，`all` 从不删除。`--live` 只更新 `latest.json`。`--no-json` 完全不写入文件，`"write_json": false` 会把它设为默认（`--json` 可以在单次运行中重新开启）。`--json -` 把 JSON 输出到 stdout 而不是写入文件，例如可以交给 `jq` 处理。它会取代终端视图（来自 `default_args` 的 `-s`、`--table` 等会被忽略），并且可以与 `--tests`/`--homework`/`--absences` 以及 `--offline`/`--max-age` 一起使用。

### 退出码

错误会以一行文字输出到 stderr（`untis: login failed: …`）；加上 `-v` 可以看到完整的错误追踪。

| 代码 | 含义 |
|---|---|
| `0` | 成功 |
| `1` | 意外错误（请报告） |
| `2` | 配置 / 安装问题（缺少配置，或没有安装 Chromium） |
| `3` | 登录失败 |
| `4` | 无法连接 WebUntis，或 WebUntis 返回了错误 |
| `5` | `--start` / `--end` / `--free`：那天没有课（输出 `-`） |
| `10` | `--changes`：自上次运行以来有变化 |
| `130` | 用 Ctrl-C 中止 |

</details>

### 登录有问题？

如果用户名和密码正确，但登录还是失败（`Form login did not redirect away from the login page`），
请检查：

1. **服务器和学校标识正确吗？** 在 `webuntis.com` 上搜索你的学校；跳转后的网址是
   `https://<server>.webuntis.com/WebUntis/?school=<slug>`。
2. **密码里有特殊字符吗？** `.env` 支持 `=` 和引号，但开头的空格会被删除。
3. **有验证码 / SSO / 双重验证（2FA）吗？** → `untis --transport browser --no-headless --form-login`
4. **截图：** 数据目录中的 `logs/login_failed.png` 显示了浏览器看到的页面。
5. **详细输出：** `untis -v`。

## 安全

`untis` 会保存个人数据，因此只允许你的用户账户读取这些数据：

- **密码：** `~/.config/untis/.env`。`untis init` 会自动设置为只有你能读取（`chmod 600`）。如果其他用户可以读取，`untis` 会发出警告。
- **登录会话：** 任何拿到 `~/.local/share/untis/sessions/storage_state.json` 的人，都可以在会话过期前冒充你。该文件以 `600` 权限创建，所在目录为 `700`。
- **输出和调试文件：** `out/`、`cache/`、`state/`（你的姓名、课表、缺勤记录）和 `logs/`（WebUntis 页面截图）同样是私有的，旧版本留下的文件会在下次运行时自动修正。分享截图前请先检查。
- **浏览器沙箱：** Chromium 默认启用沙箱。只有在 Docker 等需要的环境中，才在 `config.json` 中设置 `"browser_no_sandbox": true`（以 root 运行时会自动启用）。

```bash
untis --clear-session                                     # 退出登录：删除保存的会话
```

<details>
<summary><strong>说明</strong></summary>

- **双重验证 / 验证码**：如果学校要求一次性验证码（OTP），先用 `--no-headless --clear-session`
  运行一次并输入验证码，之后就可以用无界面模式运行。
- **考试**：数据来自 `/api/exams`。如果这个接口不可用，会从课表中推断考试
  （`source: "timetable_fallback"`）。
- **请求频率限制**：最多每 300 毫秒发送一次请求。
- **原始数据**：不加 `--keep-raw` 时，所有 `raw` 字段都会被删除。
- **存储**：在项目文件夹中，`sessions/`、`out/`、`logs/`、`config.json` 和 `.env` 都已写入
  `.gitignore`。

</details>

<details>
<summary><strong>输出格式（用于脚本 / 集成）</strong></summary>

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

</details>

<details>
<summary><strong>项目结构（给贡献者）</strong></summary>

```
pyproject.toml      # 包信息、依赖、`untis` 命令
contrib/systemd/    # 用于 --changes --notify 的用户定时器
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

</details>
