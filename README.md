# Market Risk Agent

运行一次即可抓取并计算每日美股风险数据，终端会直接输出完整 JSON，方便从 Codex 复制到 ChatGPT 制作 9:16 图片和 Short。

## 数据内容

### 波动指标

- VIX（标普500）：最新值、过去 1 年 / 3 年 / 5 年分位
- VXN（纳斯达克100）：最新值、过去 1 年 / 3 年 / 5 年分位
- VIX3M（标普500）：最新值、过去 1 年 / 3 年 / 5 年分位

### 情绪与信用

- Equity Put/Call Ratio（Cboe）
- Baa 信用利差（FRED BAA10Y）
- CNN Fear & Greed Index

### 估值

- 标普500 Trailing PE / Forward PE
- 纳斯达克100 Trailing PE / Forward PE
- 指数数据缺失时尝试使用 SPY / QQQ 代理，并在 JSON 中标注

### 综合信号

输出偏买、中立、偏卖的项目数量、综合结果，以及每项指标的判断原因。

## 在 Codex 中运行

把下面这段直接发给 Codex：

```text
请拉取 main 分支最新代码，安装 requirements.txt 中的依赖，然后运行 python daily_risk.py。
允许程序联网抓取数据。
运行完成后，请把终端输出的完整 JSON 原样放在最终回复中，不要生成图片，不要打包 ZIP，也不要只告诉我文件路径。
如果 errors 不为空，请同时说明哪些指标抓取失败，但不要编造数字。
```

## 手动运行

```powershell
py -m pip install -r requirements.txt
py daily_risk.py
```

## 输出

程序会：

1. 在终端直接打印完整 JSON。
2. 同时保存到：

```text
output/latest_data.json
```

周末或休市日显示最近可用的市场数据。若某项抓取失败，对应值保留为 `null`，错误原因写入 `errors`。
