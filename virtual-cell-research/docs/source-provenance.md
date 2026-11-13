# 来源与维护边界

本项目以独立的 Virtual Cell Research 工作流和案例体系维护。原创开发与复用修改分别登记，避免将第三方科学模型、数据或历史结果归为自身成果。

具体科研方法与独立维护范围见 [方法说明](methodology-and-scope.md)。工作流、工具与案例可以独立优化；是否提出了新模型理论、是否完成了独立预测验证，需要另有相应证据。

机器可读记录见 [source-ledger.json](source-ledger.json)：导入文件保存原路径、固定版本及原 Git blob；本地文件改变后标记为修改。新增文件按本项目实际创建记录登记，不因产品改名而改写导入来源。

案例采用另一层证据：数据提供者、URL/accession/DOI、具体资源许可、下载哈希、实际运行步骤及验证状态。完整矩阵与权重按需获取，教学文档中的小图和汇总只对应确实执行的步骤。

变更时保留 [当前许可](../LICENSE)、[原 MIT 许可](licenses/legacy-mit.md) 和 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)，更新来源台账及相关案例证据。旧文件可以重构或替换；替换说明应描述实际实现变化，不能只凭改名声称从未复用。

许可切换的范围见 [使用许可与商业授权](licensing.md)。[MIT 基准清单](licenses/mit-baseline.json) 固定原版本的文件与 Git blob；旧内容不会因被复制到新版而失去原 MIT 权利，文件整体改变也不表示其中旧部分全部转为新许可。
