# Market Risk Agent

每日生成一条 9:16 的 Market Risk Monitor Short，并上传到 finance YouTube channel（默认 unlisted）。

## 当前数据

- VIX / VXN：最新值与过去 1 / 3 / 5 年分位
- Equity Put/Call Ratio（Cboe）
- CNN Fear & Greed
- AAII Sentiment Survey
- Gold / Copper Ratio
- 10Y Treasury Yield
- QQQ Trailing PE / Forward PE（来自 `weekly-etf-report` 的 `ETF_PE_history.xlsx`）

QQQ PE 会先解析上游最新的文件 commit SHA，再按 immutable SHA 下载；如果当天上游还没更新，会有限重试，最终仍未就绪则 fail closed。

## 综合信号

`daily_risk.py` 是信号逻辑的唯一事实来源。它输出每个指标的 `signal` / `explanation`，媒体层只负责显示，不再重复实现阈值。

发布前有质量闸门：

- VIX、VXN、10Y Treasury、QQQ Forward PE 必须存在
- 至少 6 / 8 个指标有效
- 数据日期必须与 market date 一致或在允许滞后范围内
- QQQ Trailing / Forward PE coverage 必须达到最低覆盖率

质量闸门失败时不会生成并上传当天视频。

## 自动流程

GitHub Actions：`Daily Market Risk Short`

- 周一至周五 17:00 America/Toronto
- 生成 `output/latest_data.json`
- 渲染 4 张 1080×1920 卡片
- 单次 ffmpeg 编码为约 16 秒 H.264/AAC Short
- 上传 YouTube
- 将最新生产 artifact 发布到 `latest-media` branch

`main` 不再保存运行时 `output/`；最新生产结果请看 `latest-media` branch。

## 依赖

- `requirements.txt`：开发/最低版本说明
- `requirements.lock`：production 直接依赖固定版本
- Actions cache 以 `requirements.lock` hash 为 key，且缓存目录在工作树外，不会被发布步骤的 `git clean` 删除。

## 手动运行

```bash
python -m pip install -r requirements.lock
python daily_risk.py
python generate_daily_short.py --input output/latest_data.json --output-dir output/media
```

需要 ffmpeg / ffprobe 和 Noto Sans CJK 字体。
