# 免费 A 股股票池

GitHub Pages 展示静态网站，GitHub Actions 在云端工作日 15:15（北京时间）执行。电脑关机不影响运行。

## 使用前必须完成的设置

1. 在 [Tushare](https://tushare.pro/register) 注册免费账号并取得 Token。
2. 新建 GitHub 仓库并推送本项目（建议设为 Public，以使用免费 Actions/Pages 配额）。
3. 在仓库 `Settings → Secrets and variables → Actions` 新建 `TUSHARE_TOKEN`。
4. 在 `Settings → Actions → General` 将 Workflow permissions 设为 **Read and write permissions**。
5. 在 `Settings → Pages` 选择 **Deploy from a branch**，分支选 `main`，目录选 `/docs`。
6. 在 Actions 页面手动运行一次“更新股票池”，确认 Pages 地址显示初始数据。

## 重要限制

- 免费日线数据是盘后数据；任务在 15:15 起尝试拉取，并在数据尚未入库时按 5、15、30 分钟自动重试。
- GitHub 的计划任务可能延迟，故页面展示的是实际完成时间。
- `chinese-calendar` 负责法定节假日；遇临时休市，请在 `config/strategy.yaml` 的 `forced_closed_dates` 补充日期。
- Tushare 的交易日历和股票名称接口需要更高积分，免费版用本地节假日规则并可选维护 `config/stock_names.csv`。

## 维护

- 修改 `config/strategy.yaml` 即可调整示例规则。
- 每次运行的结果保存于 `docs/data/runs/`，仓库提交记录也是免费备份。
- 失败自动创建 GitHub Issue，并保存日志到 `logs/selection.log`。
- 运行 `python -m unittest discover -s tests` 执行本地测试。

本项目仅作研究和信息展示，不构成投资建议。
