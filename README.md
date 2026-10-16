# Eason Chan · Structured Archive

以**可追溯、可验证、低冗余**的数据记录陈奕迅的作品、发行、演出及其关系。

- `data/`: 规范化事实（JSON、CSV；不重复保存网页全文）
- `scripts/`: 可重现的数据导入、质量检测与 SQLite 构建
- `docs/SCHEMA.md`: 实体、唯一性、来源优先级
- `docs/ISSUES.md`: 待核验问题（只记录未解决事项）
- `sources/`: 来源清单与抓取版本记录

**数据约定**：歌名/专辑名不是主键；作品、录音版本、发行实体、演出事件均使用稳定 ID。信息冲突保留不同来源的原始说法，不以猜测覆盖。无明确依据的发行日期、首次收录专辑及安可片段均保持未知。

本地重建：`pip install -r requirements.txt && python scripts/validate.py && python scripts/build_sqlite.py`；刷新维基数据：`python scripts/sync.py`，或 GitHub Actions 手动运行 **Refresh Wikipedia structured data**。

逐日查询：`python scripts/query.py 2025-08-10`。主歌单是尚待逐场确认的地区模板映射；Encore 是维基逐日记录。

资料源：[中文维基·陈奕迅](https://zh.wikipedia.org/wiki/陳奕迅) · [陳奕迅歌曲列表](https://zh.wikipedia.org/wiki/陳奕迅歌曲列表) · [FEAR AND DREAMS](https://zh.wikipedia.org/wiki/FEAR_AND_DREAMS) · [EasonKG](https://github.com/doriscullen/EasonKG)。

Wikipedia 内容可能采用 CC BY-SA 许可：再使用保留来源、修订版本与署名；EasonKG 未找到明确 LICENSE，故仅导入客观事实及注明原出处，不直接复制原项目文本或整份 CSV。
