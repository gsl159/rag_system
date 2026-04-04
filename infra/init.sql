-- RAG System — PostgreSQL 初始化
-- 表结构由 SQLAlchemy ORM 自动创建，此文件仅添加补充索引

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

DO $$
BEGIN
  -- documents 索引
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_docs_status') THEN
    EXECUTE 'CREATE INDEX idx_docs_status ON documents(status)';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_docs_created') THEN
    EXECUTE 'CREATE INDEX idx_docs_created ON documents(created_at DESC)';
  END IF;
  -- query_logs 索引
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_qlog_created') THEN
    EXECUTE 'CREATE INDEX idx_qlog_created ON query_logs(created_at DESC)';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_qlog_cache') THEN
    EXECUTE 'CREATE INDEX idx_qlog_cache ON query_logs(cache_hit)';
  END IF;
  -- evaluations 索引
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_eval_created') THEN
    EXECUTE 'CREATE INDEX idx_eval_created ON evaluations(created_at DESC)';
  END IF;
  -- feedback 索引
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_fb_type') THEN
    EXECUTE 'CREATE INDEX idx_fb_type ON feedback(feedback)';
  END IF;
EXCEPTION WHEN undefined_table THEN
  -- 表还没创建，忽略（应用启动时 ORM 会建表）
  NULL;
END$$;
