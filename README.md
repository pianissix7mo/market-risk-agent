# Market Risk Agent

这是一个最小联网测试项目，用 Python 从 Yahoo Finance 获取：

- VIX (`^VIX`)
- VXN (`^VXN`)
- VIX3M (`^VIX3M`)
- VIX 过去 3 年百分位
- VIX / VIX3M

## 在 Codex 中测试

把整个文件夹作为项目打开，然后对 Codex 说：

```text
请检查这个项目，安装 requirements.txt 中的依赖，并运行 python daily_risk.py。
这是一个联网测试。若网络访问需要授权，请向我申请。
运行后检查 output/latest_report.md，并告诉我三个 ticker 是否都抓取成功。
不要修改指标定义，除非程序确实报错；如需修改，先说明原因，再修复并重新运行。
```

也可在 PowerShell 手动运行：

```powershell
cd 路径\market-risk-agent
py -m pip install -r requirements.txt
py daily_risk.py
```

## 输出

报告保存在：

```text
output/latest_report.md
```

休市日会显示最近交易日的收盘数据。
