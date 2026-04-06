-- RAG System — PostgreSQL 初始化
-- 表结构由 SQLAlchemy ORM 自动创建，此文件仅添加补充索引

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

DO $$
BEGIN
  -- documents
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_docs_status') THEN
    EXECUTE 'CREATE INDEX idx_docs_status ON documents(status)';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_docs_created') THEN
    EXECUTE 'CREATE INDEX idx_docs_created ON documents(created_at DESC)';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_docs_tenant') THEN
    EXECUTE 'CREATE INDEX idx_docs_tenant ON documents(tenant_id)';
  END IF;
  -- query_logs
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_qlog_created') THEN
    EXECUTE 'CREATE INDEX idx_qlog_created ON query_logs(created_at DESC)';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_qlog_cache') THEN
    EXECUTE 'CREATE INDEX idx_qlog_cache ON query_logs(cache_hit)';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_qlog_trace') THEN
    EXECUTE 'CREATE INDEX idx_qlog_trace ON query_logs(trace_id)';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_qlog_tenant') THEN
    EXECUTE 'CREATE INDEX idx_qlog_tenant ON query_logs(tenant_id)';
  END IF;
  -- evaluations
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_eval_created') THEN
    EXECUTE 'CREATE INDEX idx_eval_created ON evaluations(created_at DESC)';
  END IF;
  -- feedback
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_fb_type') THEN
    EXECUTE 'CREATE INDEX idx_fb_type ON feedback(feedback)';
  END IF;
  -- users
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_user_username') THEN
    EXECUTE 'CREATE UNIQUE INDEX idx_user_username ON users(username)';
  END IF;
  -- audit_logs
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_audit_created') THEN
    EXECUTE 'CREATE INDEX idx_audit_created ON audit_logs(created_at DESC)';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_audit_user') THEN
    EXECUTE 'CREATE INDEX idx_audit_user ON audit_logs(user_id)';
  END IF;
  -- chunks
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_chunks_doc_id') THEN
    EXECUTE 'CREATE INDEX idx_chunks_doc_id ON chunks(doc_id)';
  END IF;
EXCEPTION WHEN undefined_table THEN
  -- 表还未创建，ORM 启动时会建表，索引稍后生效
  NULL;
END$$;
