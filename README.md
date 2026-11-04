# os-experiment · os-labs 站点快照

> 目标站点：<https://os-labs.p.cs-lab.top/>（哈工大（深圳）操作系统课程实验站，mkdocs-material 生成）
> 本仓库保存该站点**全部页面的原始 HTML 快照与静态资源**，并提供可复现的 Python 抓取插件。

站点在内网（`10.249.12.224`），GitHub Actions 的公共执行器**访问不到**，所以抓取在本机执行，
再把结果提交到本仓库。下文所有命令都在仓库根目录执行。

当前快照：**52 个页面 · 371 个静态资源 · 约 73 MB**（2026-11-04）。

> 已知情况：站点自身引用了不存在的 `/js/image-captions.js`（52 个页面都在引用，服务端返回 404），
> 因此 `verify` 会提示 1 个“引用目标缺失”，这是源站的问题，不是抓取遗漏。

## 目录结构

```
.
├── oslabs_scraper/         # 抓取插件（纯 Python + requests）
│   ├── cli.py              # 命令行入口：scrape / verify / publish / sync / list
│   ├── fetcher.py          # 退避重试、限速、robots.txt、304 条件请求
│   ├── discover.py         # 解析 mkdocs 侧边栏导航 + 广度优先爬取链接
│   ├── assets.py           # 抽取 <img>/<link>/<script>/可下载附件
│   ├── manifest.py         # manifest.json：URL、sha256、ETag，用于增量抓取
│   ├── mirror.py           # 端到端编排：发现 → 下载 → 落盘 → 索引 → 清理
│   ├── publish.py          # git add / commit / push（token 不落盘）
│   └── verify.py           # 快照完整性校验
├── raw/                    # 快照：目录结构与站点 URL 一一对应
│   ├── index.html
│   ├── lab1/part1.html
│   ├── lab1/part1.assets/*.png
│   ├── stylesheets/…  javascripts/…  assets/…
│   └── manifest.json       # 抓取状态（每个文件的 URL / sha256 / 大小 / ETag）
├── INDEX.md                # 由导航树生成的站点索引（点进任意页面）
├── tests/                  # 单元测试，全部离线运行
├── scrape.sh               # 薄封装：./scrape.sh scrape
├── pyproject.toml
└── requirements.txt
```

## 快速开始

```bash
python -m pip install -r requirements.txt          # 只依赖 requests

python -m oslabs_scraper scrape                    # 抓取全站到 raw/
python -m oslabs_scraper verify                    # 校验快照是否完整、可离线打开
python -m oslabs_scraper list                      # 只看导航，不下载
```

也可以 `pip install -e .` 之后直接用 `oslabs-scrape` 命令。

## 抓取策略

| 关注点 | 做法 |
| --- | --- |
| 发现页面 | 解析 `md-nav--primary` 侧边栏得到导航页，再广度优先跟进正文里的同站链接，补齐导航外的页面 |
| 保存形式 | 原样保存服务端返回的字节，不做任何改写；因此 `raw/lab1/part1.html` 里的相对链接（`part1.assets/xxx.png`）在本地直接可用 |
| 资源 | `<img src/srcset>`、`<link rel=stylesheet/icon>`、`<script src>`、`<iframe>`、`<a>` 指向的 pdf/zip/… 一并镜像 |
| 礼貌性 | 默认 0.3s 请求间隔、指数退避重试、遵守 robots.txt、单响应 8MB 上限 |
| 增量 | `manifest.json` 记录 sha256；下次运行发 `If-None-Match`/`If-Modified-Since`，命中 304 就不重新下载；内容没变则不重写文件、不产生 diff |
| 清理 | `--prune` 删除源站已下线的页面，并回收空目录 |

常用参数：

```bash
python -m oslabs_scraper scrape --delay 0.5          # 更保守的抓取节奏
python -m oslabs_scraper scrape --prune              # 同步删除源站已删除的页面
python -m oslabs_scraper scrape --dry-run            # 只报告将发生的变化
python -m oslabs_scraper scrape --force              # 忽略缓存全量重下
python -m oslabs_scraper scrape --skip search/       # 跳过匹配子串的 URL（可重复）
```

## 提交并推送

```bash
# 1) 抓取
python -m oslabs_scraper scrape

# 2) 提交并推送（需要带 repo 写权限的 token）
export GITHUB_TOKEN=ghp_xxxxxxxx          # PowerShell: $env:GITHUB_TOKEN="ghp_xxx"
python -m oslabs_scraper sync

# 或者分两步
python -m oslabs_scraper scrape
python -m oslabs_scraper publish --message "scrape: 2026-11-04"
```

* token 只作为一次性 push URL 的内联凭证使用，**不会写入 `.git/config`**，命令输出中的 token 会被替换为 `***`。
* 想手工推送也可以：`git add -A && git commit -m "scrape" && git push`。
* token 建议用 fine-grained PAT，只授权本仓库的 `Contents: Read and write`，用完即删。

## 为什么不用 GitHub Actions 定时抓取

站点解析到 `10.249.12.224`（内网私有地址），云端 runner 无法访问。`.github/workflows/ci.yml`
只做两件不需要联网的事：跑单元测试、校验已提交的快照（`manifest.json` 哈希 + 页面内引用）。
想自动化的话，可以在能访问内网的机器上挂计划任务，定时执行 `sync`。

## 开发

```bash
python -m unittest discover -s tests -v     # 全部离线运行
```

## 说明

* 快照内容版权归课程组所有，本仓库仅用于个人离线阅读、备份与复习；请勿用于分发或替代课程页面。
* 课程明确要求独立完成实验：本快照只提供**实验说明**，不包含任何他人的实验代码或解答。
