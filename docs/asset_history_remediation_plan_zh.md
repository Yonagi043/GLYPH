# GLYPH 资产历史治理方案

版本：`1.0.0`
状态：`GATE-HISTORY` 待用户决定；未执行历史重写、远端删除或迁移

## 1. 只读基线

2026-09-04 在当前工作树执行只读审计：

- `图包与字体包/` 工作树占用约 `606 MiB`；
- Git 当前 pack 为 `547.82 MiB`；松散对象为 `56.12 MiB`；
- `.git/objects/pack/` 有 `48.91 MiB` 临时 pack 垃圾警告，未擅自删除；
- 历史最大已观察 blob 为 `17,772,300` bytes 的字体文件；
- 当前资产已进入历史，单从 tip 删除不能缩小旧 clone 的历史传输量；
- 图片和字体再分发权利尚未核验，不能未经 `GATE-RIGHTS` 上传到新存储。

基线命令：

```bash
du -sh '图包与字体包'
git count-objects -vH
git rev-list --objects --all \
  | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)'
```

临时 pack 垃圾应先用 `git fsck --full` 查明来源。清理或重打包虽然不等于历史重写，仍应在确认无进行中的 Git 操作和有可恢复备份后执行。

## 2. 方案比较

| 方案 | 历史体积 | 新 clone | 权利暴露 | 协作影响 | 适用条件 |
|---|---|---|---|---|---|
| A. 保留现状 | 不变 | 继续下载大 pack | 已有暴露不变 | 最低 | 暂停新增、先完成权利审查 |
| B. 只从当前 tip 删除 | 旧历史不变 | 默认仍取旧对象 | tip 可减少可见文件，但历史仍存在 | 低到中 | 仅用于停止后续使用，不能声称已瘦身/撤回 |
| C. 本机受限目录 + 可复现获取 | Git 后续不增长 | 新 clone 只含 metadata | 最低；获取端需单独授权 | 中 | 来源允许重复获取，或团队有受控副本 |
| D. Git LFS | 需迁移历史才显著缩小 | 按需取 LFS 对象 | LFS 端仍是再分发位置 | 中到高 | 托管、配额、权限和许可均明确 |
| E. DVC/外部研究存储 | Git 仅存指针/哈希 | 数据按权限取回 | 可做细粒度访问控制 | 中到高 | 有稳定存储、备份、成本和数据治理责任人 |
| F. `git filter-repo` 重写 | 可显著缩小 | 新 clone 较小 | 不能撤销已被第三方取得的副本 | 最高 | 所有人确认停写、备份、通知、重新 clone/rebase 与 force push |

## 3. 推荐顺序

在人工批准前只执行方案 A 的治理部分：

1. 停止继续向 Git 增加未知许可二进制；
2. 使用 TASK-01 资产目录保存 SHA-256、来源和权利状态；
3. 完成 `GATE-RIGHTS`，区分可公开、仅本地研究、metadata-only 和必须撤除的集合；
4. 由用户选择 C、D 或 E 作为后续资产存储；
5. 只有当 clone/CI 成本确实要求且所有协作者同意时，才评估 F；
6. 单独处理旧远端副本、release、fork、缓存和备份，不能把 force push 描述成法律撤回。

不推荐把 B 当作体积治理终点，也不推荐在许可未明时把文件迁到 LFS/DVC 远端。

## 4. `GATE-HISTORY` 决策包

用户需要明确选择并记录：

- 目标：仅停止增长，还是必须缩小完整历史；
- 资产去向：本机受限目录、Git LFS、DVC 或外部研究存储；
- 远端、配额、费用、保留期、备份和访问责任人；
- 许可是否允许上传到所选第三方；
- 所有活跃分支、fork、CI、部署和协作者清单；
- 停写窗口、通知文本、重新 clone/rebase 指南和回滚负责人；
- 是否允许 force push 及具体分支；
- 旧 tag/release、缓存、镜像和备份的处理范围。

缺少任何一项时，`GATE-HISTORY` 保持 `blocked`。

## 5. 可丢弃环境演练

仅在用户批准演练后，在独立临时目录操作，不在主工作树运行：

```bash
git clone --mirror <approved-source-url> glyph-history-rehearsal.git
cd glyph-history-rehearsal.git
git count-objects -vH
git verify-pack -v objects/pack/*.idx > before-verify-pack.txt

# 先保存 refs、对象统计和完整备份，再按批准范围执行 filter-repo。
# 示例路径不是授权命令，不得直接复制到主仓库：
# git filter-repo --path '图包与字体包' --invert-paths

git fsck --full
git count-objects -vH
git verify-pack -v objects/pack/*.idx > after-verify-pack.txt
```

演练报告至少比较：refs 数、对象数、pack bytes、最大 blob、受影响 commit/tag、旧/新 commit 映射、fixture 测试和重新 clone 验证。演练不得 push，且仍受 `GATE-RIGHTS` 和 `GATE-TERMS` 约束。

## 6. 获批后实施与回滚

若选择不重写历史：

- 新资产只写入批准的受控位置；
- Git 仅提交 schema、metadata、校验和及明确开放 fixture；
- CI 对新增大二进制和未知权利状态失败。

若选择重写历史：

1. 创建不可变镜像备份并离线验证；
2. 冻结写入并记录全部 refs；
3. 在镜像执行已演练的精确命令；
4. 运行 `git fsck --full`、全套测试和新 clone 验收；
5. 用户再次批准后才 force push；
6. 通知所有协作者重新 clone，禁止把旧分支直接 merge 回来；
7. 保留限期回滚镜像和 commit 映射；
8. 到期删除备份也需遵守权利与组织保留政策。

回滚不是简单再 force push：必须由指定负责人从验证过的镜像恢复全部 refs，并再次通知协作者。TASK-01 当前没有执行上述任何写操作。
