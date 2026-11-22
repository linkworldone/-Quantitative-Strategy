# 本地实时永续合约模拟交易
只使用 Binance 或 OKX 公开行情，不需要密钥，不具备下单代码。实时订阅标记价格/永续 ticker，估算短线波动，运行偏空的规则策略，只有向上波动异动时允许做多。虚拟资金 10,000 美元，名义仓位上限 3 倍；单笔风险预算 0.5%，总止损风险上限 2%，止损距离为近期波动的 2.5 倍并限制在 0.6%-4%，单边手续费估算 0.05%。净值从峰值回撤 10% 后停止开新仓。

Windows 启动：
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    python live_paper.py --exchange binance --days 60
OKX：将 exchange 改为 okx。两个月使用 60 天；三个月另跑 90 天。交易记录保存至 trades.csv，净值保存至 equity.csv，状态保存至 paper_state.json。Ctrl+C 可停止，重启会恢复模拟账户。

这是研究原型：用实时行情近似成交，尚未模拟资金费、点差、深度滑点、精确合约面值和强平规则；策略也未经验证。新闻、AI、最大供给、市场情绪及链上转账尚未接入，不能假称已用于决策。聪明钱方向无法从公开账户多空比直接识别。不得以本程序结果证明未来收益。

