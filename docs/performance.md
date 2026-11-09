# 最终打磨与性能验证

基线：`0867dd79`。使用同一 Chromium 156、1440 × 1000 视口、七条订阅、40 ms 延迟、10 Mibit/s 吞吐、4 倍 CPU 降速；每项五次取中位数。原始结果见 [performance.json](performance.json)。Python 服务使用相同的临时数据库和四个 Waitress 线程，浏览器测量时不启动调度器。

## 修改与版本

Basecoat 0.3.11 → 官方稳定版 1.1.0。实施时官方文档与 npm latest 均高于任务书中的 1.0.2，未使用预发布或旧版兼容 CSS。全部 Python 锁定版本经 PyPI 正式发布记录逐项核对后保持原值，详见 [依赖核对](dependencies.md)。Python 保持 3.15.2，pip 保持 26.3，生产依赖未增加。

界面统一采用新版属性、44px 控件、中性选中状态及缩短后的文案；普通保存静默完成，保存栏仅在有修改时可见并保留布局空间。会话过期后在当前页面重新登录，内存草稿保留，失败请求不会自动重放。Bark 地址不持久化到浏览器。导航统一使用普通页面 URL，移除 hash 恢复逻辑及无用测试服务脚手架。

后台刷新串行协调，失败保留内容；相同响应不再重建 DOM。保留搜索、分类、提交响应时的滚动位置和合理焦点。资源生成器支持 `--check`，自动化测试检查源码与 JS/CSS/gzip 一致，生成结果不含时间戳。

## 浏览器结果

单位：KiB；请求包含本地缓存资源，实际传输另计。FCP/LCP 单位 ms。

| 页面 / 缓存 | 前请求 / 网络 | 后请求 / 网络 | 前传输 | 后传输 | 前 FCP / LCP | 后 FCP / LCP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 首页 / 冷 | 5 / 5 | 5 / 5 | 59.35 | 69.78 | 200 / 200 | 220 / 220 |
| 首页 / 热 | 5 / 1 | 5 / 1 | 3.11 | 3.24 | 80 / 80 | 76 / 76 |
| 订阅 / 冷 | 5 / 5 | 5 / 5 | 60.05 | 70.50 | 208 / 208 | 224 / 224 |
| 订阅 / 热 | 5 / 1 | 5 / 1 | 3.80 | 3.95 | 88 / 88 | 88 / 88 |
| 设置 / 冷 | 5 / 5 | 5 / 5 | 58.63 | 69.11 | 180 / 180 | 204 / 204 |
| 设置 / 热 | 5 / 1 | 5 / 1 | 2.38 | 2.56 | 76 / 76 | 68 / 68 |

| 生产文本资源 | 前原始 / gzip KiB | 后原始 / gzip KiB |
| --- | ---: | ---: |
| JS | 15.58 / 5.08 | 16.60 / 5.23 |
| CSS | 140.09 / 14.12 | 237.07 / 24.25 |

默认 Vega 预构建 CSS 升级后，CSS gzip 增加约 10.13 KiB，各页冷缓存传输增加约 10.4 KiB，冷缓存 FCP/LCP 增加 16–24 ms。保留官方预构建资源，获得统一组件规范及后续维护路径；没有引入 Tailwind 编译、兼容层或自制 CSS 裁剪器。这个取舍有明确的传输成本，不将其描述为性能提升。热缓存仍仅一个实际网络请求。

| 页面 / 冷缓存 | 前 JS Heap MiB | 后 JS Heap MiB | 前交互 ms | 后交互 ms |
| --- | ---: | ---: | ---: | ---: |
| 首页 | 2.65 | 2.66 | 14.7 | 13.4 |
| 订阅 | 3.09 | 3.09 | 9.6 | 12.2 |
| 设置 | 2.80 | 2.80 | 18.4 | 7.4 |

堆在相同采样点读取，未强制 GC。交互采样包含后续两帧的调度时间，不等于真实 INP，几毫秒差异有帧调度抖动。请求量和堆基本持平。

## Docker 与兼容性

在 `192.168.5.118`（RHEL10、amd64、Docker 29.9.1）使用独立镜像、容器和卷，生产启动启用八个 Waitress 线程及原调度器，网络为 none，预填相同的当日缓存。原始结果见 [docker-validation.json](docker-validation.json)。RSS 连续采样五次取中位数，不能与 macOS 的绝对数值横向比较。

| 项目 | 基线 | 打磨后 |
| --- | ---: | ---: |
| 镜像 MiB | 111.95 | 112.07 |
| 空闲 RSS MiB | 39.87 | 40.10 |
| 操作后 RSS MiB | 40.26 | 40.43 |

生产健康检查、UID 10001、运行环境无 Node/npm、CRUD/批量保存及版本冲突、设置/备份/排序/续费撤销、gzip/HEAD/ETag/304/Range/缓存均通过。两版重启后数据与会话保留；基线数据卷直接挂到新版后，原会话、七条订阅、分类顺序、续费标记、Schema 与 user_version 均保留，SQLite integrity_check 为 ok。测试容器和卷已清理。

## 测试与复现

当前回归：25 项开发环境 Python 测试、21 项 Playwright 测试通过；资源一致性检查、Ruff 检查与格式检查通过。Docker 内 24 项运行时 Python 测试通过，源码/压缩器一致性测试另在开发环境执行。开发环境和生产镜像 pip check 均通过。真实 iPhone Bark 收件未实测，通知成功/失败由隔离替身覆盖。

```sh
python -m pip install -r requirements-dev.txt
python -m pip check
python tools/prepare_assets.py --check
python -m unittest discover -s tests -v
python -m tests.browser -v
ruff check app tests tools
ruff format --check app tests tools

mkdir -p /tmp/barque-polish-before
git archive 0867dd79 | tar -x -C /tmp/barque-polish-before
python -m tests.performance --baseline /tmp/barque-polish-before --runs 5 --output /tmp/performance.json

docker build -t barque-before:validation /tmp/barque-polish-before
docker build -t barque-after:validation .
python -m tests.docker_validation --before barque-before:validation --after barque-after:validation --output /tmp/docker.json
```

Python 资源生成与部署仍不需要 Node 或新的构建工具。

## 最终收尾复核（基准 e4ab1031）

统一认证失效入口并避免重复打开登录对话框；续费等待后台刷新后重新核对订阅、账期和已付状态，状态变化时要求重新操作。补齐 Basecoat 按钮规范、Bark 显隐图标和 JavaScript 格式，清理重复 CSS。

当轮 25 项 Python、18 项浏览器回归通过，Ruff、pip check 和资源一致性检查通过。独立 Docker 镜像完成 HTTP、配置操作、重启及已有数据兼容验证。业务模块、依赖、API 和持久化格式未改动。

生产 JS gzip 从 5,356 增至 5,450 字节，应用 CSS gzip 从 1,909 降至 1,906 字节；Basecoat 资源和请求路径不变。本轮未重新测量 FCP、LCP 或浏览器堆，以上页面性能数据仍为上一轮实测。
