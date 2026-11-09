# 依赖核对

实施时通过官方 PyPI JSON API 逐项核对所有锁定依赖，排除预发布和撤回版本。现有 Python 依赖均已是最新稳定版，保持精确锁定。

| 依赖 | 最新稳定版 | 官方记录 |
| --- | --- | --- |
| anyio | 4.16.0 | [PyPI](https://pypi.org/pypi/anyio/json) |
| blinker | 1.9.0 | [PyPI](https://pypi.org/pypi/blinker/json) |
| certifi | 2026.10.23 | [PyPI](https://pypi.org/pypi/certifi/json) |
| click | 8.5.1 | [PyPI](https://pypi.org/pypi/click/json) |
| Flask | 3.1.3 | [PyPI](https://pypi.org/pypi/Flask/json) |
| h11 | 0.16.0 | [PyPI](https://pypi.org/pypi/h11/json) |
| httpcore | 1.0.9 | [PyPI](https://pypi.org/pypi/httpcore/json) |
| httpx | 0.28.1 | [PyPI](https://pypi.org/pypi/httpx/json) |
| idna | 3.20 | [PyPI](https://pypi.org/pypi/idna/json) |
| itsdangerous | 2.2.0 | [PyPI](https://pypi.org/pypi/itsdangerous/json) |
| Jinja2 | 3.1.6 | [PyPI](https://pypi.org/pypi/Jinja2/json) |
| MarkupSafe | 3.0.4 | [PyPI](https://pypi.org/pypi/MarkupSafe/json) |
| pip | 26.3 | [PyPI](https://pypi.org/pypi/pip/json) |
| playwright | 1.64.1 | [PyPI](https://pypi.org/pypi/playwright/json) |
| python-dateutil | 4.0.0 | [PyPI](https://pypi.org/pypi/python-dateutil/json) |
| rcssmin | 1.3.0 | [PyPI](https://pypi.org/pypi/rcssmin/json) |
| rjsmin | 1.3.0 | [PyPI](https://pypi.org/pypi/rjsmin/json) |
| ruff | 0.17.4 | [PyPI](https://pypi.org/pypi/ruff/json) |
| tzdata | 2026.6 | [PyPI](https://pypi.org/pypi/tzdata/json) |
| waitress | 3.0.2 | [PyPI](https://pypi.org/pypi/waitress/json) |
| Werkzeug | 3.1.9 | [PyPI](https://pypi.org/pypi/Werkzeug/json) |

Python 保持官方稳定版 3.15.2，Alpine 生产镜像构建与依赖检查通过：[Python 正式发布](https://www.python.org/downloads/release/python-3152/)。

Basecoat 由 0.3.11 升级到 1.1.0。官方文档及 npm `latest` 均为 1.1.0，已高于任务书中的 1.0.2；遵循实施时最新正式稳定版的要求。使用官方默认 Vega 预构建 CSS、新版属性和原生控件，不加载兼容 CSS 或未使用的组件 JS。

- [官方安装文档](https://basecoatui.com/installation/)
- [官方 npm 元数据](https://registry.npmjs.org/basecoat-css/latest)
- [正式发布](https://github.com/hunvreus/basecoat/releases)

生产依赖未新增。开发环境与最终生产镜像 `pip check` 均通过。

Playwright 的重要传递依赖亦核对并精确锁定（均为现有依赖，无新增运行包）：

| 依赖 | 稳定版 | 官方记录 |
| --- | --- | --- |
| pyee | 14.0.0（兼容范围内） | [PyPI](https://pypi.org/pypi/pyee/json) |
| greenlet | 3.5.6 | [PyPI](https://pypi.org/pypi/greenlet/json) |
| typing_extensions | 4.16.0 | [PyPI](https://pypi.org/pypi/typing_extensions/json) |

pyee 的全局最新正式版为 16.0.1，但当前最新 Playwright 1.64.1 明确要求 `pyee>=13,<15`。因此锁定兼容范围内最新的 14.0.0，避免为传递依赖版本号破坏官方依赖约束。
