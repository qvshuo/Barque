<p align="center">
  <img src="frontend/public/logo.png?v=3" alt="Barque logo" width="120">
</p>

# Barque

订阅提醒工具，在到期前通过 Bark 自动向 iPhone 推送通知。

## 截图

![Barque 订阅](./docs/assets/screenshot.png)

## 快速开始

```shell
git clone https://github.com/qvshuo/Barque.git --depth=1
cd Barque
cp docker-compose.example.yml docker-compose.yml
# 编辑 docker-compose.yml，设置访问密码
docker compose up -d --build
```

打开 `http://localhost:8080`，使用设置的密码登录。

## 数据与升级

所有配置、订阅、续费状态、通知去重记录和汇率缓存均保存在 Docker 数据卷的 `/app/data/barque.sqlite3`。

已有版本升级时，保留原来的数据挂载和 Compose 配置，再执行：

```shell
docker compose up -d --build --pull always
```
