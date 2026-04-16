# 微信公众号发布后端

这是和 `demo_backend` 分开的独立版本，专门用于微信公众号草稿发布。

## 目录说明

- `backend/app.py`
  FastAPI 入口
- `backend/config.py`
  微信公众号配置读取
- `backend/service.py`
  公众号草稿发布服务骨架
- `assets/`
  放封面图和正文图片
- `.env.example`
  微信公众号 API 占位配置

## 当前实现了什么

- `GET /health`
- `GET /api/wechat/publish/info`
  查看公众号发布所需配置、素材目录、当前模式
- `POST /api/wechat/publish/mock-draft`
  生成一条 mock 的公众号草稿任务

## 当前还没真正发请求到微信的部分

以下是已经预留好的后端步骤，但默认先不自动调用：

- 获取 `access_token`
- 上传封面图拿 `thumb_media_id`
- 上传正文图片拿微信图片 URL
- 调草稿箱接口创建草稿
- 调发布草稿接口自动发布

你后面只要把 `.env` 填好，就可以继续把这些方法接成真实 API 调用。

## 素材目录

封面图默认位置：
- `wechat/assets/cover.jpg`

正文图片目录：
- `wechat/assets/body/`

推荐：
- 封面优先用 JPG
- 先用 900x383 或接近比例的 JPG 作为封面调试
- 正文插图也建议 JPG/PNG

## 需要申请和填写的配置

去微信公众号后台获取：
- `WECHAT_APP_ID`
- `WECHAT_APP_SECRET`
- `WECHAT_TOKEN`（如果你后面要做服务器回调验证）
- `WECHAT_ENCODING_AES_KEY`（如果你后面做安全模式回调）

注意：
- 调公众号接口的后端机器公网出口 IP 要加到该公众号自己的 IP 白名单里

## 运行

```bash
uvicorn wechat.backend.app:app --reload --host 0.0.0.0 --port 8090
```
