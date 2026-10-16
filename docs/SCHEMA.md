# 数据模型 v0.1

## 实体与唯一性
- **work**（作品）：人工确认的同一首作品；`work_id` 不以歌名生成。粤语／国语改词版本是否同一作品须标明关系，不自动合并。
- **recording**（录音）：`recording_id` 对应具体录音、重录、现场版本；一首作品可多次录音。
- **release**（发行实体）：`release_id` 区分发行时间、地区、介质、版本；同名专辑不保证唯一。`release_group_id` 合并确认为同一专辑的多个发行版。
- **release_track**：唱片具体版次、盘号、曲序及录音的多对多关系；不靠歌名判断“初次收录”。
- **tour / show**：`show_id` 为巡演内编号＋巡演 ID；演出日期只是属性，不用日期作为主键。
- **performance**：一个场次内一个表演位置，包含 `section`（MAIN/ENCORE）、`round`、`position`、`kind`（FULL/SNIPPET/MEDLEY/MASHUP/UNKNOWN）；组曲成员另设顺序关系。
- **assertion**（来源事实）：每条事实保留 `source_id`、`revision`、`raw_value`、`status`；冲突并存，不覆盖。

## 数据层
- `data/easonkg/*.jsonl`：EasonKG 候选歌曲与关系断言，**未经逐首核验，非主表**。
- `data/wiki/*`：MediaWiki 修订号固定的巡演原始结构化片段；不储存冗长百科原文。
- `data/db/eason.sqlite`：由脚本生成，可供 API/网页查询，不作独立事实源。
- 证据等级：已逐条复核 > Wikipedia 结构化资料 > EasonKG 自动抽取 > 粉丝内容；**来源优先级不等于真实性保证**。

## 精确性规则
1. Unicode 保留原样；另存展示别名与搜索键，不做不可逆繁简折叠。
2. 同名作品、专辑、国语／粤语版、同名重发行都允许；不得用标题 UNIQUE。
3. `首次发行` 必须有可比较的正式发行日期与版本证据；未证实设 NULL。
4. Encore 每个分段和清唱分别记录；原表无法分割时只保存 raw，禁止猜测歌序。
5. 自动产生的场次模板必须标记 `unverified_template`，不能冒充当晚真实歌单。
6. 导入必须幂等；缺失值不推断；源修订变化可复现且留痕。
