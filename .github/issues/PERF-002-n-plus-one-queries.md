# PERF-002: 消除 N+1 查询风险

## 严重级别
**P1 - Medium** (数据库性能)

## 问题描述
`src/audiobook_studio/api/books.py` `projects.py` `chapters.py` 列表接口：
```python
projects = await db.scalars(select(Project))
for p in projects:
    chapters = p.chapters  # 惰性加载 → N 次 SELECT
```

## 修复方案
1. 统一使用 `selectinload` 预加载：
   ```python
   stmt = select(Project).options(
       selectinload(Project.chapters).selectinload(Chapter.segments)
   )
   ```
2. 关键列表接口默认 `joinedload` 单层，深层 `selectinload`
3. 引入 `sqlalchemy.orm.raiseload('*')` 在不应惰性加载的模型上显式禁用
4. 开发环境 `echo=True` + `pytest` 断言查询数

## 验收标准
- [ ] `SQLALCHEMY_ECHO=true pytest tests/unit/api/test_books.py` 单测查询数 ≤ 3
- [ ] `pytest tests/unit/api/test_projects.py::test_list_projects_with_chapters` 断言无惰性加载
- [ ] 生产慢查询日志无 `SELECT ... FROM chapters WHERE project_id = ?` 重复模式

## 关联文件
- `src/audiobook_studio/api/books.py`
- `src/audiobook_studio/api/projects.py`
- `src/audiobook_studio/api/chapters.py`
- `src/audiobook_studio/models/__init__.py` (关系定义加 `lazy="selectin"`)