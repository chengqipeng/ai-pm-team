"""修复 tenant_id 不一致问题 — 将 tenant_id=1 的历史数据迁移到 DEFAULT_TENANT_ID"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.core.context import DEFAULT_TENANT_ID, DEFAULT_USER_ID
from src.store.pg_pool import get_conn


def main():
    with get_conn() as conn:
        cur = conn.cursor()

        # 1. 查看受影响数据量
        print("=== 迁移前数据统计 ===")
        for table in ['ai_conversation', 'ai_trace', 'ai_trace_span', 'ai_message', 'ai_message_ext']:
            try:
                cur.execute(f"SELECT tenant_id, COUNT(*) FROM {table} GROUP BY tenant_id ORDER BY tenant_id")
                rows = cur.fetchall()
                for tid, cnt in rows:
                    print(f"  {table}: tenant_id={tid}, count={cnt}")
            except Exception as e:
                print(f"  {table}: 查询失败 - {e}")
                conn.rollback()

        # 2. 修复 ai_conversation
        cur.execute("UPDATE ai_conversation SET tenant_id = %s WHERE tenant_id = 1", (DEFAULT_TENANT_ID,))
        print(f"\n[修复] ai_conversation: {cur.rowcount} 行 tenant_id 1 → {DEFAULT_TENANT_ID}")

        # 3. 修复 ai_trace
        cur.execute("UPDATE ai_trace SET tenant_id = %s WHERE tenant_id = 1", (DEFAULT_TENANT_ID,))
        print(f"[修复] ai_trace: {cur.rowcount} 行 tenant_id 1 → {DEFAULT_TENANT_ID}")

        # 4. 修复 ai_trace_span
        cur.execute("UPDATE ai_trace_span SET tenant_id = %s WHERE tenant_id = 1", (DEFAULT_TENANT_ID,))
        print(f"[修复] ai_trace_span: {cur.rowcount} 行 tenant_id 1 → {DEFAULT_TENANT_ID}")

        # 5. 修复 ai_message
        cur.execute("UPDATE ai_message SET tenant_id = %s WHERE tenant_id = 1", (DEFAULT_TENANT_ID,))
        print(f"[修复] ai_message: {cur.rowcount} 行 tenant_id 1 → {DEFAULT_TENANT_ID}")

        # 6. 修复 ai_message_ext
        cur.execute("UPDATE ai_message_ext SET tenant_id = %s WHERE tenant_id = 1", (DEFAULT_TENANT_ID,))
        print(f"[修复] ai_message_ext: {cur.rowcount} 行 tenant_id 1 → {DEFAULT_TENANT_ID}")

        # 7. 修复 user_id=0 的会话记录
        cur.execute("""
            UPDATE ai_conversation
            SET user_id = %s, created_by = %s, updated_by = %s
            WHERE tenant_id = %s AND user_id = 0
        """, (DEFAULT_USER_ID, DEFAULT_USER_ID, DEFAULT_USER_ID, DEFAULT_TENANT_ID))
        print(f"[修复] ai_conversation user_id=0: {cur.rowcount} 行 → user_id={DEFAULT_USER_ID}")

        # 提交
        conn.commit()
        print("\n✅ 数据迁移完成！")

        # 8. 验证
        print("\n=== 迁移后数据统计 ===")
        for table in ['ai_conversation', 'ai_trace', 'ai_trace_span']:
            cur.execute(f"SELECT tenant_id, COUNT(*) FROM {table} GROUP BY tenant_id ORDER BY tenant_id")
            rows = cur.fetchall()
            for tid, cnt in rows:
                print(f"  {table}: tenant_id={tid}, count={cnt}")


if __name__ == "__main__":
    main()
