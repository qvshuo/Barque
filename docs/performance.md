# 前端迁移与性能验证

基线：[08d9955](https://github.com/qvshuo/Barque/commit/08d995537a653695f090b2d0e3aa869fa8b8d158)，已核对为迁移开始时 GitHub `main` 的最新提交。测量日期：2026-11-09。原始结果见 [performance.json](performance.json)，复现脚本为 `tests/performance.py`。

## 测量条件

同一台 macOS 27.2 ARM64 设备、Python 3.15.2、Chromium 156.0.8078.4，1440 × 1000 视口，简体中文、Asia/Shanghai 时区和亮色主题。两版服务均使用 Waitress、4 个 HTTP 线程，不启动调度线程，不访问真实 Bark 或外部汇率服务。固定使用相同的七条订阅、七个分类、付款日期和配置；每页五次测量，报告中位数。

浏览器统一限制为 40 ms 网络延迟、10 Mibit/s 吞吐和 4 倍 CPU 降速。冷缓存使用新的浏览器上下文；热缓存在同一上下文重新加载相同地址。登录请求在采样前完成。传输量取 CDP `Network.loadingFinished.encodedDataLength`，包含 HTTP 响应头；请求数排除内联 data URI，保留缓存命中的逻辑资源请求，并另列实际传输请求数。

FCP、LCP 在交互前采集。JS Heap 取相同采样点的 `Runtime.getHeapUsage.usedSize`，未强制 GC；这是浏览器堆快照，不是稳定存活对象大小。交互响应从搜索、添加分类或显示 Bark 地址触发到后续两次动画帧，包含帧调度开销，不等同于真实用户 INP。

## 源码和生产资源

源代码统计包含模板与客户端 JS/CSS；排除第三方预构建资源、压缩产物和旧版注明自动生成的 `shadcn.css`。计数采用物理行，保留正常格式，不以压成单行获得行数收益。

| 项目 | 迁移前 | 迁移后 |
| --- | ---: | ---: |
| 维护的前端源文件 | 26 | 10 |
| 维护的前端代码行 | 3209 | 1357 |
| 含旧生成样式的全部前端源行 | 3839 | 1357 |

下表单位为 KiB。gzip 使用 level 9、mtime 0；这是文件级比较，不含响应头。页面实际传输另列。

| 生产资源 | 前原始 | 后原始 | 前 gzip | 后 gzip |
| --- | ---: | ---: | ---: | ---: |
| JavaScript | 900.89 | 15.58 | 282.62 | 5.08 |
| CSS（含 Basecoat） | 50.78 | 140.09 | 9.07 | 14.12 |
| 运行时图片 | 329.17 | 67.92 | 不压缩 | 不压缩 |

CSS 增大来自固定版本 Basecoat 的完整预构建样式，替代原来按使用情况裁剪的 Tailwind 输出。没有浏览器编译器，也未引入新的 CSS 构建。两版 JS 与 CSS 的合计 gzip 体积由 291.69 KiB 降为 19.20 KiB。

## HTML 与页面加载

服务端渲染使首个 HTML 包含可用内容，因此 HTML 原始体积增加，同时减少初始化脚本及后续 API 获取。下表的 HTML 传输体积是实际协商后的响应正文；迁移前 HTML 未压缩。

| 页面 | 前 HTML 原始 / 传输 KiB | 后 HTML 原始 / 传输 KiB |
| --- | ---: | ---: |
| 首页 | 0.75 / 0.75 | 19.75 / 2.55 |
| 管理订阅 | 0.75 / 0.75 | 38.43 / 3.24 |
| 设置 | 0.75 / 0.75 | 5.23 / 1.82 |

请求列表示「逻辑请求 / 实际传输请求」，传输量单位 KiB；FCP、LCP 单位 ms。

| 页面 / 缓存 | 前请求 | 后请求 | 前传输 | 后传输 | 前 FCP / LCP | 后 FCP / LCP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 首页 / 冷 | 6 / 6 | 5 / 5 | 512.62 | 59.38 | 572 / 572 | 196 / 196 |
| 首页 / 热 | 6 / 4 | 5 / 1 | 7.76 | 3.11 | 180 / 180 | 76 / 76 |
| 管理订阅 / 冷 | 7 / 7 | 5 / 5 | 511.37 | 60.08 | 564 / 564 | 208 / 208 |
| 管理订阅 / 热 | 7 / 5 | 5 / 1 | 6.50 | 3.80 | 172 / 172 | 92 / 92 |
| 设置 / 冷 | 6 / 6 | 5 / 5 | 508.08 | 58.65 | 572 / 648 | 180 / 180 |
| 设置 / 热 | 6 / 4 | 5 / 1 | 3.21 | 2.38 | 168 / 232 | 72 / 72 |

## 浏览器堆和交互

| 页面 / 缓存 | 前 Heap MiB | 后 Heap MiB | 前交互 ms | 后交互 ms |
| --- | ---: | ---: | ---: | ---: |
| 首页 / 冷 | 8.36 | 2.64 | 16.4 | 6.4 |
| 首页 / 热 | 13.35 | 4.55 | 12 | 17.4 |
| 管理订阅 / 冷 | 9.14 | 3.09 | 28.3 | 10 |
| 管理订阅 / 热 | 15.93 | 4.57 | 22.7 | 7.3 |
| 设置 / 冷 | 6.30 | 2.80 | 9.5 | 12.8 |
| 设置 / 热 | 10.62 | 4.40 | 16.1 | 9.8 |

帧级交互测量有调度抖动，几毫秒差异不作为单独的性能结论。应结合加载、资源、堆大小和重复提交等功能回归判断。

## 图片

| 图片 | 迁移前字节 | 迁移后字节 | 处理 |
| --- | ---: | ---: | --- |
| Logo | 216598 | 34822 | 512 → 256 像素，覆盖 README 120 CSS 像素的双倍分辨率；透明、无损 WebP 编码 |
| favicon | 88760 | 6914 | 保留 16、32、48 像素，移除 64、128、256 图层 |
| Apple 图标 | 31710 | 27815 | 保持 180 × 180，清理元数据、无损重压缩；RGBA 逐像素相同 |
| 文档截图 | 105027 | 43594 | 更新为移除环形图后的真实界面，WebP；不计入网页首屏资源 |

Logo 保留原图形、透明度和颜色；显示尺寸保持不变。页面标明图片宽高，所有图片继续由本服务托管。旧 `/logo.png` 入口继续返回正确 MIME 类型的本地 Logo，无重复 PNG 副本。

## 服务内存与 Docker

服务 RSS 由同一测量进程启动后及完成全部常规浏览器操作后读取，单位 MiB；没有强制回收。

| 状态 | 迁移前 RSS | 迁移后 RSS |
| --- | ---: | ---: |
| 空闲 | 75.78 | 75.98 |
| 常规操作后 | 76.56 | 78.06 |

Python 服务空闲内存基本持平，操作后可能因模板和资源缓存略增，不宣称后端内存降低。浏览器堆明显减少。

已在 SSH 主机 `192.168.5.118`（RHEL10、Linux x86_64、Docker 29.9.1）完成两版原始 Dockerfile 的实际构建与容器运行验收。完整结果见 [docker-validation.json](docker-validation.json)，复现脚本为 `tests/docker_validation.py`。

| Docker 项目 | 迁移前 | 迁移后 |
| --- | ---: | ---: |
| 镜像大小（字节） | 119524611 | 117383326 |
| 镜像大小（MiB） | 113.99 | 111.95 |
| 生产服务空闲 RSS（MiB） | 40.04 | 39.97 |
| 常规操作后 RSS（MiB） | 40.19 | 40.30 |
| 镜像内 Python 回归测试 | 17 项通过 | 24 项通过 |

镜像减少 2141285 字节，即约 2.04 MiB（1.79%）。大小取同一 Docker 引擎的 `docker image inspect .Size`，不代表镜像仓库的压缩下载大小或共享层的独占磁盘用量。两版使用相同 `python:3.15.2-alpine` 基础镜像，并共享前七个文件系统层；旧版最终阶段本来也是 Python，体积收益主要来自静态资源减少。

此处 RSS 与上方 macOS 测量分开比较：容器以生产命令 `python -m app.main` 启动，启用原有八个 Waitress 线程及调度器，仍使用同一套七条订阅。读取容器 PID 1 的 `/proc/1/status`，每个状态连续采样五次取中位数。空闲内存基本持平，操作后增加约 0.11 MiB。测试预填当日币种及人民币汇率缓存，使用 `--network none`，HTTP 验证在容器回环地址完成，无外部推送或端口发布。

容器验收通过以下检查：

- 原 Dockerfile 健康检查为 `healthy`，以 UID 10001 运行，运行镜像中均无 Node/npm。
- 经实际 Waitress 验证登录、认证隔离、全部页面、订阅 CRUD、分类排序、批量保存及冲突、设置、导入导出、无效 Bark 地址、续费标记与撤销。
- 实际静态资源的 gzip、HEAD、ETag/304，以及新版 SSR、动态 gzip、Range、二进制不 gzip、敏感页面 no-store 与 406 协商。
- 两版分别重启后保留配置、七条订阅、分类顺序、续费标记和登录会话。
- 将旧版实际数据卷直接挂载新镜像，原登录会话继续有效；导出配置、分类顺序、续费标记均保留，SQLite Schema 与 `user_version` 一致，完整性检查为 `ok`。

测试使用独立镜像、容器和数据卷；临时容器及数据卷已清理并核对，现有服务继续运行。构建镜像保留为 `barque-migration-before:validation-4czafm` 和 `barque-migration-after:validation-4czafm`，构建及测试日志位于远程 `/tmp/barque-docker-validation.4CZAfM`。

## 功能和 HTTP 回归

24 项 Python 测试、13 项 Chromium 浏览器测试通过，Ruff 检查与格式检查通过。原有 17 项 Python 测试保留；旧图表专属浏览器用例删除，其余行为迁移至 Python Playwright，并扩展测试。

- 订阅及分类新增、编辑、删除、排序、空分类、整组保存、版本冲突和失败恢复。
- 原生日期、金额、币种、提醒状态、未知币种、搜索分类筛选和续费标记；续费及汇率计算继续由原模块完成。
- 未保存离开确认、刷新和前后历史保护、Dialog 焦点与 Escape、移动端明暗布局。
- Bark 未保存地址测试的成功与失败、设置保存、JSON 导入导出及失败后的反馈清理。
- 认证、退出、退出失败时保留草稿、保存期间会话过期、重复保存及重复续费提交保护。
- 服务端转义、动态文本、认证隔离、静态路径穿越、资源版本和预压缩完整性。
- gzip / identity / 禁用编码与 406、HEAD、ETag、304、Range、二进制不 gzip、动态及错误响应 no-store。
- 页面数据读取失败有可重试页面，内部错误详情不输出；公开 JSON API 的处理路径保持原状。

实际 iPhone Bark 收件未实测；Bark 网络结果通过隔离测试替身覆盖。测量数据规模固定为七条订阅，不能据此推断大规模数据或其他设备上的绝对性能。

## 复现

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/playwright install chromium
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m tests.browser -v
.venv/bin/ruff check app tests tools
.venv/bin/ruff format --check app tests tools

mkdir -p /tmp/barque-before
git archive 08d9955 | tar -x -C /tmp/barque-before
(cd /tmp/barque-before/frontend && npm ci && npm run build)
.venv/bin/python -m tests.performance --baseline /tmp/barque-before --runs 5 --output /tmp/barque-performance.json
```

Node 仅用于复现旧版生产产物；迁移后开发验证、资源准备和生产运行均使用 Python。性能脚本为两版分别创建临时数据库，退出时回收服务和数据；不会连接日常使用的实例。

在具有 Docker 的主机上复现镜像验收：

```sh
mkdir -p /tmp/barque-before
git archive 08d9955 | tar -x -C /tmp/barque-before
docker build -t barque-before:validation /tmp/barque-before
docker build -t barque-after:validation .
python3 -m tests.docker_validation --before barque-before:validation --after barque-after:validation --output /tmp/barque-docker-validation.json
```

该验证脚本仅需 Python 标准库和 Docker CLI，自动创建并清理独立测试容器与数据卷。镜像内回归测试另外以只读方式挂载测试目录运行，不向生产镜像安装开发依赖。
