-- RAG System — PostgreSQL 初始化
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 此文件仅作补充索引；表结构由 SQLAlchemy ORM 自动创建

-- 索引（ORM 创建表后生效）
-- 注意：若表尚未创建，这些语句会在首次连接后由应用层触发

DO $$
BEGIN
  -- 文档索引
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_docs_status') THEN
    EXECUTE 'CREATE INDEX idx_docs_status ON documents(status)';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_docs_created') THEN
    EXECUTE 'CREATE INDEX idx_docs_created ON documents(created_at DESC)';
  END IF;
  -- 查询日志索引
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_qlog_created') THEN
    EXECUTE 'CREATE INDEX idx_qlog_created ON query_logs(created_at DESC)';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_qlog_cache') THEN
    EXECUTE 'CREATE INDEX idx_qlog_cache ON query_logs(cache_hit)';
  END IF;
  -- 评估索引
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_eval_created') THEN
    EXECUTE 'CREATE INDEX idx_eval_created ON evaluations(created_at DESC)';
  END IF;
  -- 反馈索引
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_fb_type') THEN
    EXECUTE 'CREATE INDEX idx_fb_type ON feedback(feedback)';
  END IF;
EXCEPTION WHEN undefined_table THEN
  -- 表还没创建，忽略（应用启动时 ORM 会建表）
  NULL;
END$$;
