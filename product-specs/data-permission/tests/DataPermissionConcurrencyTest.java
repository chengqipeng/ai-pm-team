// package removed for standalone execution
// 注意：独立运行时使用内嵌的 TransmittableThreadLocal 模拟类
// 生产环境使用 com.alibaba.ttl.TransmittableThreadLocal

import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.function.Supplier;

/**
 * 数据权限上下文隔离 — 多线程并发验证测试。
 *
 * 验证目标：
 *   1. TransmittableThreadLocal 在阶段分离后不会发生上下文污染
 *   2. PermissionCondition（不可变值对象）在多线程共享时无竞态条件
 *   3. 嵌套 executeWithRoute（share 表查询）不会残留 TTL 值
 *   4. 异常场景下 TTL 被正确清理
 *   5. 高并发下各线程的路由表名互不干扰
 *   6. 线程池复用线程时 TTL 上下文正确隔离（原生 ThreadLocal 会泄漏的场景）
 *
 * 运行方式：javac DataPermissionConcurrencyTest.java && java DataPermissionConcurrencyTest
 * 无需 Spring / MyBatis / 数据库连接，纯内存模拟。
 */
public class DataPermissionConcurrencyTest {

    // ═══════════════════════════════════════════════════════════
    // 模拟 TransmittableThreadLocal（独立运行，不依赖 TTL jar）
    // 生产代码使用 com.alibaba.ttl.TransmittableThreadLocal
    // ═══════════════════════════════════════════════════════════

    /**
     * 简化版 TransmittableThreadLocal 模拟。
     * 核心行为：继承 InheritableThreadLocal，支持在线程池提交任务时
     * 通过 capture/replay/restore 机制传递上下文。
     * 生产环境直接使用 com.alibaba.ttl.TransmittableThreadLocal。
     */
    static class TransmittableThreadLocal<T> extends InheritableThreadLocal<T> {
        // 全局注册表：跟踪所有活跃的 TTL 实例
        private static final CopyOnWriteArrayList<TransmittableThreadLocal<?>> registry = new CopyOnWriteArrayList<>();

        public TransmittableThreadLocal() {
            registry.add(this);
        }

        /** 捕获当前线程所有 TTL 的快照 */
        static Map<TransmittableThreadLocal<?>, Object> capture() {
            Map<TransmittableThreadLocal<?>, Object> snapshot = new HashMap<>();
            for (TransmittableThreadLocal<?> ttl : registry) {
                Object val = ttl.get();
                if (val != null) {
                    snapshot.put(ttl, val);
                }
            }
            return snapshot;
        }

        /** 将快照回放到当前线程，返回备份 */
        @SuppressWarnings("unchecked")
        static Map<TransmittableThreadLocal<?>, Object> replay(Map<TransmittableThreadLocal<?>, Object> snapshot) {
            Map<TransmittableThreadLocal<?>, Object> backup = capture();
            // 清除当前线程所有 TTL
            for (TransmittableThreadLocal<?> ttl : registry) {
                ttl.remove();
            }
            // 回放快照
            for (Map.Entry<TransmittableThreadLocal<?>, Object> entry : snapshot.entrySet()) {
                ((TransmittableThreadLocal<Object>) entry.getKey()).set(entry.getValue());
            }
            return backup;
        }

        /** 恢复备份 */
        @SuppressWarnings("unchecked")
        static void restore(Map<TransmittableThreadLocal<?>, Object> backup) {
            for (TransmittableThreadLocal<?> ttl : registry) {
                ttl.remove();
            }
            for (Map.Entry<TransmittableThreadLocal<?>, Object> entry : backup.entrySet()) {
                ((TransmittableThreadLocal<Object>) entry.getKey()).set(entry.getValue());
            }
        }
    }

    /** TTL 包装的 Runnable — 模拟 TtlRunnable */
    static class TtlRunnable implements Runnable {
        private final Map<TransmittableThreadLocal<?>, Object> captured;
        private final Runnable delegate;

        TtlRunnable(Runnable delegate) {
            this.captured = TransmittableThreadLocal.capture();
            this.delegate = delegate;
        }

        @Override
        public void run() {
            Map<TransmittableThreadLocal<?>, Object> backup = TransmittableThreadLocal.replay(captured);
            try {
                delegate.run();
            } finally {
                TransmittableThreadLocal.restore(backup);
            }
        }

        static Runnable get(Runnable runnable) {
            return new TtlRunnable(runnable);
        }
    }

    /** TTL 包装的 Callable — 模拟 TtlCallable */
    static class TtlCallable<V> implements Callable<V> {
        private final Map<TransmittableThreadLocal<?>, Object> captured;
        private final Callable<V> delegate;

        TtlCallable(Callable<V> delegate) {
            this.captured = TransmittableThreadLocal.capture();
            this.delegate = delegate;
        }

        @Override
        public V call() throws Exception {
            Map<TransmittableThreadLocal<?>, Object> backup = TransmittableThreadLocal.replay(captured);
            try {
                return delegate.call();
            } finally {
                TransmittableThreadLocal.restore(backup);
            }
        }

        static <V> Callable<V> get(Callable<V> callable) {
            return new TtlCallable<>(callable);
        }
    }

    // ═══════════════════════════════════════════════════════════
    // 模拟核心组件（与生产代码结构一致）
    // ═══════════════════════════════════════════════════════════

    /** 模拟 DynamicTableNameHolder — 使用 TransmittableThreadLocal */
    static final class DynamicTableNameHolder {
        private static final TransmittableThreadLocal<String> TABLE_NAME = new TransmittableThreadLocal<>();

        static void set(String tableName) { TABLE_NAME.set(tableName); }
        static String get() { return TABLE_NAME.get(); }
        static void clear() { TABLE_NAME.remove(); }

        static <T> T executeWith(String tableName, Supplier<T> action) {
            set(tableName);
            try {
                return action.get();
            } finally {
                clear();
            }
        }

        static void runWith(String tableName, Runnable action) {
            set(tableName);
            try {
                action.run();
            } finally {
                clear();
            }
        }
    }

    /** 模拟 ShardConstants */
    static final class ShardConstants {
        static final String TABLE_PREFIX = "p_tenant_data_";
        static String tableName(int index) { return TABLE_PREFIX + index; }
    }

    /** 模拟 DataPermission 配置 */
    static final class DataPermission {
        private final Integer defaultAccess;
        private final Integer ownerAccess;

        DataPermission(Integer defaultAccess, Integer ownerAccess) {
            this.defaultAccess = defaultAccess;
            this.ownerAccess = ownerAccess;
        }

        Integer getDefaultAccess() { return defaultAccess; }
        Integer getOwnerAccess() { return ownerAccess; }
    }

    /** 模拟 UserSubject */
    static final class UserSubject {
        static final int DEPART = 1;
        private final int type;
        private final String subjectApiKey;

        UserSubject(int type, String subjectApiKey) {
            this.type = type;
            this.subjectApiKey = subjectApiKey;
        }

        int getType() { return type; }
        String getSubjectApiKey() { return subjectApiKey; }
    }

    // ═══════════════════════════════════════════════════════════
    // PermissionCondition — 不可变值对象（与设计文档一致）
    // ═══════════════════════════════════════════════════════════

    static final class PermissionCondition {
        private final boolean skip;
        private final Long userId;
        private final DataPermission config;
        private final List<UserSubject> subjects;
        private final List<Long> visibleDataIds;
        private final String skipReason;

        private PermissionCondition(boolean skip, Long userId, DataPermission config,
                                     List<UserSubject> subjects, List<Long> visibleDataIds,
                                     String skipReason) {
            this.skip = skip;
            this.userId = userId;
            this.config = config;
            this.subjects = subjects != null ? Collections.unmodifiableList(new ArrayList<>(subjects)) : null;
            this.visibleDataIds = visibleDataIds != null ? Collections.unmodifiableList(new ArrayList<>(visibleDataIds)) : null;
            this.skipReason = skipReason;
        }

        static PermissionCondition skipWith(String reason) {
            return new PermissionCondition(true, null, null, null, null, reason);
        }

        static PermissionCondition filterWith(Long userId, DataPermission config,
                                               List<UserSubject> subjects, List<Long> visibleDataIds) {
            return new PermissionCondition(false, userId, config, subjects, visibleDataIds, null);
        }

        boolean isSkip() { return skip; }
        Long getUserId() { return userId; }
        List<Long> getVisibleDataIds() { return visibleDataIds; }
        List<UserSubject> getSubjects() { return subjects; }
        DataPermission getConfig() { return config; }

        /**
         * 模拟权限条件拼接 — 纯内存操作。
         * 返回生成的 SQL 条件片段（用于验证正确性）。
         */
        String applyTo() {
            if (skip) return "SKIP:" + skipReason;

            StringBuilder sb = new StringBuilder("AND (owner_id = ").append(userId);
            if (config.getDefaultAccess() != null && config.getDefaultAccess() > 0 && subjects != null) {
                for (UserSubject s : subjects) {
                    if (s.getType() == UserSubject.DEPART) {
                        sb.append(" OR depart_api_key = '").append(s.getSubjectApiKey()).append("'");
                    }
                }
            }
            if (visibleDataIds != null && !visibleDataIds.isEmpty()) {
                sb.append(" OR id IN (").append(visibleDataIds).append(")");
            }
            sb.append(")");
            return sb.toString();
        }

        @Override
        public String toString() {
            if (skip) return "PermissionCondition{SKIP, reason=" + skipReason + "}";
            return "PermissionCondition{userId=" + userId
                    + ", subjects=" + (subjects != null ? subjects.size() : 0)
                    + ", visibleDataIds=" + (visibleDataIds != null ? visibleDataIds.size() : 0) + "}";
        }
    }

    // ═══════════════════════════════════════════════════════════
    // 模拟服务层（记录调用时的 ThreadLocal 状态用于断言）
    // ═══════════════════════════════════════════════════════════

    /** 记录每次"元数据查询"时 ThreadLocal 的值 */
    static final ConcurrentLinkedQueue<String> metaQueryThreadLocalSnapshots = new ConcurrentLinkedQueue<>();

    /** 记录每次"业务数据查询"时 ThreadLocal 的值 */
    static final ConcurrentLinkedQueue<String> bizQueryThreadLocalSnapshots = new ConcurrentLinkedQueue<>();

    /** 模拟 DataPermissionConfigService.get() — 内部会触发元数据查询 */
    static DataPermission mockConfigServiceGet(long tenantId, String entityApiKey) {
        // 记录此刻 ThreadLocal 的值（应该为 null）
        String snapshot = DynamicTableNameHolder.get();
        metaQueryThreadLocalSnapshots.add(snapshot == null ? "NULL" : snapshot);

        // 模拟元数据查询延迟
        sleepQuietly(ThreadLocalRandom.current().nextInt(1, 5));

        // 返回模拟配置
        return new DataPermission(1, 2); // defaultAccess=1, ownerAccess=2
    }

    /** 模拟 UserSubjectService.getUserSubjects() */
    static List<UserSubject> mockGetUserSubjects(long tenantId, Long userId) {
        String snapshot = DynamicTableNameHolder.get();
        metaQueryThreadLocalSnapshots.add(snapshot == null ? "NULL" : snapshot);

        return Arrays.asList(
                new UserSubject(UserSubject.DEPART, "dept_" + userId),
                new UserSubject(UserSubject.DEPART, "dept_parent_" + userId)
        );
    }

    /** 模拟 DataShareQueryService.getVisibleDataIds() — 使用独立的分表路由 */
    static List<Long> mockGetVisibleDataIds(long tenantId, String entityApiKey, List<UserSubject> subjects) {
        // share 表查询使用独立的 executeWithRoute
        int shareTableIndex = Math.abs((entityApiKey + "_share").hashCode()) % 100;
        String shareTableName = "p_data_share_" + shareTableIndex;

        return DynamicTableNameHolder.executeWith(shareTableName, () -> {
            // 验证此刻 ThreadLocal 是 share 表名
            String current = DynamicTableNameHolder.get();
            assert shareTableName.equals(current) :
                    "share 查询时 ThreadLocal 应为 " + shareTableName + "，实际为 " + current;

            sleepQuietly(ThreadLocalRandom.current().nextInt(2, 8));

            // 返回模拟的可见数据 ID
            List<Long> ids = new ArrayList<>();
            for (int i = 0; i < 5; i++) {
                ids.add(tenantId * 1000 + i);
            }
            return ids;
        });
    }

    /** 模拟 buildCondition — 与设计文档中的 DataPermissionFilter.buildCondition 一致 */
    static PermissionCondition buildCondition(long tenantId, String entityApiKey, Long userId) {
        if (userId == null) {
            return PermissionCondition.skipWith("internal_call");
        }

        // 查元数据配置（此时应无 ThreadLocal 污染）
        DataPermission config = mockConfigServiceGet(tenantId, entityApiKey);
        if (config == null) {
            return PermissionCondition.skipWith("no_config");
        }
        if (config.getDefaultAccess() != null && config.getDefaultAccess() == 2) {
            return PermissionCondition.skipWith("public_access");
        }

        // 展开用户权限主体
        List<UserSubject> subjects = mockGetUserSubjects(tenantId, userId);

        // 查 share 表（独立路由上下文）
        List<Long> visibleDataIds = mockGetVisibleDataIds(tenantId, entityApiKey, subjects);

        // share 查询结束后，ThreadLocal 应已被清理
        String afterShare = DynamicTableNameHolder.get();
        assert afterShare == null :
                "share 查询后 ThreadLocal 应为 null，实际为 " + afterShare;

        return PermissionCondition.filterWith(userId, config, subjects, visibleDataIds);
    }

    /** 模拟 routeService.executeWithRoute */
    static <T> T executeWithRoute(long tenantId, String entityApiKey, Supplier<T> action) {
        int tableIndex = Math.abs((tenantId + "_" + entityApiKey).hashCode()) % 2000;
        String tableName = ShardConstants.tableName(tableIndex);
        return DynamicTableNameHolder.executeWith(tableName, action);
    }

    /** 模拟业务数据查询 — 记录 ThreadLocal 状态 */
    static String mockBizDataQuery(String entityApiKey, PermissionCondition cond) {
        String tableName = DynamicTableNameHolder.get();
        bizQueryThreadLocalSnapshots.add(tableName == null ? "NULL" : tableName);

        // 模拟 SQL 执行
        String sqlCondition = cond.applyTo();
        sleepQuietly(ThreadLocalRandom.current().nextInt(1, 3));

        return "SELECT * FROM " + tableName + " WHERE entity_api_key = '" + entityApiKey
                + "' AND delete_flg = 0 " + sqlCondition;
    }

    // ═══════════════════════════════════════════════════════════
    // 测试用例
    // ═══════════════════════════════════════════════════════════

    static int passed = 0, failed = 0;
    static final List<String> errors = new ArrayList<>();

    static void assertCondition(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    static void sleepQuietly(int ms) {
        try { Thread.sleep(ms); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
    }

    @FunctionalInterface
    interface ThrowingRunnable { void run() throws Exception; }

    static void test(String name, ThrowingRunnable testFn) {
        try {
            testFn.run();
            passed++;
            System.out.println("  ✅ " + name);
        } catch (Throwable e) {
            failed++;
            errors.add(name + ": " + e.getMessage());
            System.out.println("  ❌ " + name + ": " + e.getMessage());
        }
    }

    // ═══════════════════════════════════════════════════════════
    // main — 运行所有测试
    // ═══════════════════════════════════════════════════════════

    public static void main(String[] args) throws Exception {
        System.out.println("\n══════════════════════════════════════════════════");
        System.out.println("  数据权限上下文隔离 — 多线程并发验证");
        System.out.println("══════════════════════════════════════════════════");

        // ── 测试 1：单线程基本流程验证 ──
        System.out.println("\n📦 1. 单线程基本流程");

        test("阶段1(buildCondition)时 ThreadLocal 为 null", () -> {
            metaQueryThreadLocalSnapshots.clear();
            PermissionCondition cond = buildCondition(292193, "account", 1001L);
            assertCondition(!cond.isSkip(), "应返回需要过滤的条件");
            assertCondition(cond.getUserId().equals(1001L), "userId 应为 1001");
            // 验证所有元数据查询时 ThreadLocal 都为 null
            for (String snapshot : metaQueryThreadLocalSnapshots) {
                assertCondition("NULL".equals(snapshot),
                        "元数据查询时 ThreadLocal 应为 NULL，实际为: " + snapshot);
            }
        });

        test("阶段2(executeWithRoute)内 ThreadLocal 为业务表名", () -> {
            bizQueryThreadLocalSnapshots.clear();
            PermissionCondition cond = buildCondition(292193, "account", 1001L);

            String result = executeWithRoute(292193, "account", () ->
                    mockBizDataQuery("account", cond));

            assertCondition(result.contains("p_tenant_data_"), "SQL 应包含分片表名");
            for (String snapshot : bizQueryThreadLocalSnapshots) {
                assertCondition(snapshot.startsWith("p_tenant_data_"),
                        "业务查询时 ThreadLocal 应为 p_tenant_data_*，实际为: " + snapshot);
            }
        });

        test("executeWithRoute 结束后 ThreadLocal 被清理", () -> {
            executeWithRoute(292193, "account", () -> "ok");
            assertCondition(DynamicTableNameHolder.get() == null,
                    "executeWithRoute 结束后 ThreadLocal 应为 null");
        });

        test("userId=null 时返回 SKIP", () -> {
            PermissionCondition cond = buildCondition(292193, "account", null);
            assertCondition(cond.isSkip(), "userId=null 应跳过过滤");
        });

        test("PermissionCondition 不可变性验证", () -> {
            List<UserSubject> subjects = new ArrayList<>();
            subjects.add(new UserSubject(UserSubject.DEPART, "dept_1"));
            List<Long> ids = new ArrayList<>(Arrays.asList(1L, 2L, 3L));

            PermissionCondition cond = PermissionCondition.filterWith(
                    1001L, new DataPermission(1, 2), subjects, ids);

            // 修改原始列表不应影响 PermissionCondition
            subjects.add(new UserSubject(UserSubject.DEPART, "dept_2"));
            ids.add(4L);

            assertCondition(cond.getSubjects().size() == 1,
                    "subjects 应为不可变副本，不受原始列表修改影响");
            assertCondition(cond.getVisibleDataIds().size() == 3,
                    "visibleDataIds 应为不可变副本");

            // 尝试修改不可变列表应抛异常
            try {
                cond.getSubjects().add(new UserSubject(UserSubject.DEPART, "hack"));
                throw new AssertionError("不可变列表不应允许 add 操作");
            } catch (UnsupportedOperationException e) {
                // 预期行为
            }

            try {
                cond.getVisibleDataIds().add(999L);
                throw new AssertionError("不可变列表不应允许 add 操作");
            } catch (UnsupportedOperationException e) {
                // 预期行为
            }
        });

        // ── 测试 2：多线程并发验证 ──
        System.out.println("\n📦 2. 多线程并发验证（模拟 HTTP 并发请求）");

        test("50 线程并发 listPage — ThreadLocal 互不干扰", () -> {
            metaQueryThreadLocalSnapshots.clear();
            bizQueryThreadLocalSnapshots.clear();

            int threadCount = 50;
            ExecutorService executor = Executors.newFixedThreadPool(threadCount);
            CountDownLatch startLatch = new CountDownLatch(1);  // 所有线程同时开始
            CountDownLatch doneLatch = new CountDownLatch(threadCount);
            AtomicInteger errorCount = new AtomicInteger(0);
            ConcurrentHashMap<String, String> threadResults = new ConcurrentHashMap<>();

            for (int i = 0; i < threadCount; i++) {
                final long tenantId = 100000 + i;
                final String entityApiKey = (i % 3 == 0) ? "account" : (i % 3 == 1) ? "opportunity" : "lead";
                final long userId = 2000 + i;
                final String threadName = "req-" + i;

                executor.submit(() -> {
                    Thread.currentThread().setName(threadName);
                    try {
                        startLatch.await(); // 等待所有线程就绪

                        // ═══ 模拟改造后的 listPage 调用 ═══

                        // 阶段 1：分表上下文之外
                        String beforeBuild = DynamicTableNameHolder.get();
                        if (beforeBuild != null) {
                            errorCount.incrementAndGet();
                            threadResults.put(threadName, "ERROR: buildCondition 前 ThreadLocal 不为 null: " + beforeBuild);
                            return;
                        }

                        PermissionCondition cond = buildCondition(tenantId, entityApiKey, userId);

                        String afterBuild = DynamicTableNameHolder.get();
                        if (afterBuild != null) {
                            errorCount.incrementAndGet();
                            threadResults.put(threadName, "ERROR: buildCondition 后 ThreadLocal 不为 null: " + afterBuild);
                            return;
                        }

                        // 阶段 2：分表上下文之内
                        String sql = executeWithRoute(tenantId, entityApiKey, () -> {
                            String tableName = DynamicTableNameHolder.get();
                            if (tableName == null || !tableName.startsWith("p_tenant_data_")) {
                                return "ERROR: 业务查询时 ThreadLocal 异常: " + tableName;
                            }
                            return mockBizDataQuery(entityApiKey, cond);
                        });

                        String afterRoute = DynamicTableNameHolder.get();
                        if (afterRoute != null) {
                            errorCount.incrementAndGet();
                            threadResults.put(threadName, "ERROR: executeWithRoute 后 ThreadLocal 不为 null: " + afterRoute);
                            return;
                        }

                        // 验证 SQL 包含正确的条件
                        if (!sql.contains("owner_id = " + userId)) {
                            errorCount.incrementAndGet();
                            threadResults.put(threadName, "ERROR: SQL 缺少正确的 owner_id 条件: " + sql);
                            return;
                        }

                        threadResults.put(threadName, "OK: " + sql.substring(0, Math.min(80, sql.length())));

                    } catch (Throwable e) {
                        errorCount.incrementAndGet();
                        threadResults.put(threadName, "EXCEPTION: " + e.getMessage());
                    } finally {
                        doneLatch.countDown();
                    }
                });
            }

            startLatch.countDown(); // 同时释放所有线程
            boolean completed = doneLatch.await(30, TimeUnit.SECONDS);
            executor.shutdown();

            assertCondition(completed, "所有线程应在 30 秒内完成");
            assertCondition(errorCount.get() == 0,
                    "应无错误，实际错误数: " + errorCount.get()
                            + "，详情: " + threadResults.entrySet().stream()
                            .filter(e -> e.getValue().startsWith("ERROR") || e.getValue().startsWith("EXCEPTION"))
                            .map(e -> e.getKey() + "=" + e.getValue())
                            .reduce((a, b) -> a + "; " + b).orElse("none"));

            // 验证所有元数据查询时 ThreadLocal 都为 null
            long pollutedCount = metaQueryThreadLocalSnapshots.stream()
                    .filter(s -> !"NULL".equals(s)).count();
            assertCondition(pollutedCount == 0,
                    "所有元数据查询时 ThreadLocal 应为 NULL，被污染次数: " + pollutedCount);
        });

        test("100 线程混合场景 — 有权限/无权限/内部调用并发", () -> {
            int threadCount = 100;
            ExecutorService executor = Executors.newFixedThreadPool(threadCount);
            CountDownLatch startLatch = new CountDownLatch(1);
            CountDownLatch doneLatch = new CountDownLatch(threadCount);
            AtomicInteger errorCount = new AtomicInteger(0);

            for (int i = 0; i < threadCount; i++) {
                final int idx = i;
                executor.submit(() -> {
                    try {
                        startLatch.await();

                        long tenantId = 200000 + idx;
                        String entityApiKey = "entity_" + (idx % 5);
                        Long userId;

                        // 混合场景：1/3 内部调用(null), 1/3 普通用户, 1/3 不同用户
                        if (idx % 3 == 0) {
                            userId = null; // 内部调用
                        } else {
                            userId = (long) (3000 + idx);
                        }

                        // 阶段 1
                        PermissionCondition cond = buildCondition(tenantId, entityApiKey, userId);

                        // 验证 ThreadLocal 干净
                        if (DynamicTableNameHolder.get() != null) {
                            errorCount.incrementAndGet();
                            return;
                        }

                        // 阶段 2
                        executeWithRoute(tenantId, entityApiKey, () -> {
                            String tableName = DynamicTableNameHolder.get();
                            if (tableName == null) {
                                errorCount.incrementAndGet();
                                return null;
                            }
                            // applyTo 是纯内存操作
                            cond.applyTo();
                            return null;
                        });

                        // 验证清理
                        if (DynamicTableNameHolder.get() != null) {
                            errorCount.incrementAndGet();
                        }

                    } catch (Throwable e) {
                        errorCount.incrementAndGet();
                    } finally {
                        doneLatch.countDown();
                    }
                });
            }

            startLatch.countDown();
            boolean completed = doneLatch.await(30, TimeUnit.SECONDS);
            executor.shutdown();

            assertCondition(completed, "所有线程应在 30 秒内完成");
            assertCondition(errorCount.get() == 0,
                    "混合场景应无错误，实际错误数: " + errorCount.get());
        });

        // ── 测试 3：嵌套 ThreadLocal 场景 ──
        System.out.println("\n📦 3. 嵌套 ThreadLocal 场景");

        test("share 表查询的嵌套 executeWithRoute 不残留", () -> {
            int threadCount = 30;
            ExecutorService executor = Executors.newFixedThreadPool(threadCount);
            CountDownLatch startLatch = new CountDownLatch(1);
            CountDownLatch doneLatch = new CountDownLatch(threadCount);
            AtomicInteger errorCount = new AtomicInteger(0);

            for (int i = 0; i < threadCount; i++) {
                final int idx = i;
                executor.submit(() -> {
                    try {
                        startLatch.await();

                        // 模拟 buildCondition 中的 share 表查询
                        String beforeShare = DynamicTableNameHolder.get();
                        if (beforeShare != null) {
                            errorCount.incrementAndGet();
                            return;
                        }

                        // share 表查询（独立 executeWithRoute）
                        String shareTable = "p_data_share_" + (idx % 50);
                        List<Long> ids = DynamicTableNameHolder.executeWith(shareTable, () -> {
                            String current = DynamicTableNameHolder.get();
                            if (!shareTable.equals(current)) {
                                errorCount.incrementAndGet();
                            }
                            sleepQuietly(ThreadLocalRandom.current().nextInt(1, 5));
                            return Arrays.asList((long) idx, (long) (idx + 1));
                        });

                        // share 查询后 ThreadLocal 应为 null
                        String afterShare = DynamicTableNameHolder.get();
                        if (afterShare != null) {
                            errorCount.incrementAndGet();
                            return;
                        }

                        // 然后进入业务数据的 executeWithRoute
                        String bizTable = "p_tenant_data_" + (idx % 2000);
                        DynamicTableNameHolder.executeWith(bizTable, () -> {
                            String current = DynamicTableNameHolder.get();
                            if (!bizTable.equals(current)) {
                                errorCount.incrementAndGet();
                            }
                            return null;
                        });

                        // 最终 ThreadLocal 应为 null
                        if (DynamicTableNameHolder.get() != null) {
                            errorCount.incrementAndGet();
                        }

                    } catch (Throwable e) {
                        errorCount.incrementAndGet();
                    } finally {
                        doneLatch.countDown();
                    }
                });
            }

            startLatch.countDown();
            boolean completed = doneLatch.await(30, TimeUnit.SECONDS);
            executor.shutdown();

            assertCondition(completed, "所有线程应在 30 秒内完成");
            assertCondition(errorCount.get() == 0,
                    "嵌套场景应无错误，实际错误数: " + errorCount.get());
        });

        // ── 测试 4：异常场景 ──
        System.out.println("\n📦 4. 异常场景下的 ThreadLocal 清理");

        test("executeWithRoute 内部抛异常 — ThreadLocal 仍被清理", () -> {
            int threadCount = 20;
            ExecutorService executor = Executors.newFixedThreadPool(threadCount);
            CountDownLatch startLatch = new CountDownLatch(1);
            CountDownLatch doneLatch = new CountDownLatch(threadCount);
            AtomicInteger errorCount = new AtomicInteger(0);

            for (int i = 0; i < threadCount; i++) {
                final int idx = i;
                executor.submit(() -> {
                    try {
                        startLatch.await();

                        String tableName = "p_tenant_data_" + idx;
                        try {
                            DynamicTableNameHolder.executeWith(tableName, () -> {
                                if (idx % 2 == 0) {
                                    throw new RuntimeException("模拟 SQL 异常: table " + tableName);
                                }
                                return "ok";
                            });
                        } catch (RuntimeException e) {
                            // 预期异常，忽略
                        }

                        // 无论是否抛异常，ThreadLocal 都应被清理
                        String afterException = DynamicTableNameHolder.get();
                        if (afterException != null) {
                            errorCount.incrementAndGet();
                        }

                    } catch (Throwable e) {
                        errorCount.incrementAndGet();
                    } finally {
                        doneLatch.countDown();
                    }
                });
            }

            startLatch.countDown();
            boolean completed = doneLatch.await(30, TimeUnit.SECONDS);
            executor.shutdown();

            assertCondition(completed, "所有线程应在 30 秒内完成");
            assertCondition(errorCount.get() == 0,
                    "异常场景 ThreadLocal 应被清理，实际错误数: " + errorCount.get());
        });

        test("share 查询抛异常 — 不影响后续业务数据路由", () -> {
            // 模拟 share 查询失败，但业务数据查询仍应正常
            String bizTable = "p_tenant_data_42";

            try {
                DynamicTableNameHolder.executeWith("p_data_share_17", () -> {
                    throw new RuntimeException("share 表查询超时");
                });
            } catch (RuntimeException e) {
                // 预期
            }

            // ThreadLocal 应已清理
            assertCondition(DynamicTableNameHolder.get() == null,
                    "share 异常后 ThreadLocal 应为 null");

            // 业务数据路由应正常
            String result = DynamicTableNameHolder.executeWith(bizTable, () -> {
                return DynamicTableNameHolder.get();
            });
            assertCondition(bizTable.equals(result),
                    "业务数据路由应正常，期望 " + bizTable + "，实际 " + result);
        });

        // ── 测试 5：PermissionCondition 跨线程共享 ──
        System.out.println("\n📦 5. PermissionCondition 跨线程共享安全性");

        test("同一个 PermissionCondition 被多线程并发使用", () -> {
            // 预构建一个 PermissionCondition
            PermissionCondition shared = PermissionCondition.filterWith(
                    1001L,
                    new DataPermission(1, 2),
                    Arrays.asList(new UserSubject(UserSubject.DEPART, "dept_sales")),
                    Arrays.asList(100L, 200L, 300L)
            );

            int threadCount = 50;
            ExecutorService executor = Executors.newFixedThreadPool(threadCount);
            CountDownLatch startLatch = new CountDownLatch(1);
            CountDownLatch doneLatch = new CountDownLatch(threadCount);
            AtomicInteger errorCount = new AtomicInteger(0);
            ConcurrentHashMap<String, String> results = new ConcurrentHashMap<>();

            for (int i = 0; i < threadCount; i++) {
                final int idx = i;
                executor.submit(() -> {
                    try {
                        startLatch.await();

                        // 每个线程用不同的分片表，但共享同一个 PermissionCondition
                        String tableName = "p_tenant_data_" + idx;
                        String sql = DynamicTableNameHolder.executeWith(tableName, () -> {
                            String condition = shared.applyTo();
                            return "SELECT * FROM " + DynamicTableNameHolder.get()
                                    + " WHERE " + condition;
                        });

                        // 验证 SQL 包含正确的表名和条件
                        if (!sql.contains(tableName)) {
                            errorCount.incrementAndGet();
                            results.put("thread-" + idx, "ERROR: SQL 表名错误: " + sql);
                            return;
                        }
                        if (!sql.contains("owner_id = 1001")) {
                            errorCount.incrementAndGet();
                            results.put("thread-" + idx, "ERROR: SQL 条件错误: " + sql);
                            return;
                        }
                        if (!sql.contains("dept_sales")) {
                            errorCount.incrementAndGet();
                            results.put("thread-" + idx, "ERROR: SQL 缺少部门条件: " + sql);
                            return;
                        }

                        results.put("thread-" + idx, "OK");

                    } catch (Throwable e) {
                        errorCount.incrementAndGet();
                        results.put("thread-" + idx, "EXCEPTION: " + e.getMessage());
                    } finally {
                        doneLatch.countDown();
                    }
                });
            }

            startLatch.countDown();
            boolean completed = doneLatch.await(30, TimeUnit.SECONDS);
            executor.shutdown();

            assertCondition(completed, "所有线程应在 30 秒内完成");
            assertCondition(errorCount.get() == 0,
                    "共享 PermissionCondition 应无错误，实际错误数: " + errorCount.get());
        });

        // ── 测试 6：模拟改造前的 BUG（对照组）──
        System.out.println("\n📦 6. 对照组 — 验证改造前的 BUG 确实存在");

        test("改造前：在 executeWithRoute 内部查元数据 — ThreadLocal 被污染", () -> {
            AtomicBoolean polluted = new AtomicBoolean(false);

            // 模拟改造前的错误写法
            executeWithRoute(292193, "account", () -> {
                // 此时 ThreadLocal = "p_tenant_data_xxx"
                String currentTable = DynamicTableNameHolder.get();

                // 在分表上下文内调用元数据查询
                // 元数据查询会看到 ThreadLocal 不为 null → 表名被替换 → BUG!
                if (currentTable != null && currentTable.startsWith("p_tenant_data_")) {
                    polluted.set(true);
                }

                return null;
            });

            assertCondition(polluted.get(),
                    "改造前的写法确实会导致 ThreadLocal 污染（对照组验证通过）");
        });

        test("改造后：在 executeWithRoute 之前查元数据 — ThreadLocal 干净", () -> {
            // 阶段 1：分表上下文之外
            String snapshot = DynamicTableNameHolder.get();
            assertCondition(snapshot == null, "阶段 1 ThreadLocal 应为 null");

            PermissionCondition cond = buildCondition(292193, "account", 1001L);

            snapshot = DynamicTableNameHolder.get();
            assertCondition(snapshot == null, "buildCondition 后 ThreadLocal 应为 null");

            // 阶段 2：分表上下文之内
            executeWithRoute(292193, "account", () -> {
                cond.applyTo(); // 纯内存操作
                return null;
            });

            snapshot = DynamicTableNameHolder.get();
            assertCondition(snapshot == null, "executeWithRoute 后 ThreadLocal 应为 null");
        });

        // ── 测试 7：线程池复用场景（TTL 核心价值）──
        System.out.println("\n📦 7. 线程池复用场景 — TTL 上下文隔离");

        test("固定线程池复用线程 — TTL 不泄漏到下一个任务", () -> {
            // 使用极小的线程池（2 个线程），强制线程复用
            ExecutorService pool = Executors.newFixedThreadPool(2);
            AtomicInteger errorCount = new AtomicInteger(0);
            int taskCount = 20;
            CountDownLatch doneLatch = new CountDownLatch(taskCount);

            for (int i = 0; i < taskCount; i++) {
                final int idx = i;
                // 使用 TtlRunnable 包装，模拟生产环境的 TTL 线程池
                pool.submit(TtlRunnable.get(() -> {
                    try {
                        // 每个任务开始时 TTL 应为 null（不应继承上一个任务的值）
                        String before = DynamicTableNameHolder.get();
                        if (before != null) {
                            System.err.println("  [LEAK] task-" + idx + " 开始时 TTL 不为 null: " + before);
                            errorCount.incrementAndGet();
                            return;
                        }

                        // 模拟 listPage 的完整流程
                        PermissionCondition cond = buildCondition(100000 + idx, "account", (long) idx);

                        String afterBuild = DynamicTableNameHolder.get();
                        if (afterBuild != null) {
                            errorCount.incrementAndGet();
                            return;
                        }

                        String tableName = "p_tenant_data_" + (idx % 2000);
                        DynamicTableNameHolder.executeWith(tableName, () -> {
                            cond.applyTo();
                            sleepQuietly(1); // 模拟 SQL 执行
                            return null;
                        });

                        // 任务结束时 TTL 应为 null
                        String after = DynamicTableNameHolder.get();
                        if (after != null) {
                            System.err.println("  [LEAK] task-" + idx + " 结束时 TTL 不为 null: " + after);
                            errorCount.incrementAndGet();
                        }
                    } finally {
                        doneLatch.countDown();
                    }
                }));
            }

            boolean completed = doneLatch.await(30, TimeUnit.SECONDS);
            pool.shutdown();

            assertCondition(completed, "所有任务应在 30 秒内完成");
            assertCondition(errorCount.get() == 0,
                    "线程池复用场景应无 TTL 泄漏，实际错误数: " + errorCount.get());
        });

        test("线程池中故意不清理 TTL — 验证 TtlRunnable 的隔离效果", () -> {
            ExecutorService pool = Executors.newFixedThreadPool(1); // 单线程池，强制复用
            AtomicInteger errorCount = new AtomicInteger(0);

            // 任务 1：设置 TTL 但"忘记"清理（模拟 BUG 代码）
            CountDownLatch task1Done = new CountDownLatch(1);
            pool.submit(TtlRunnable.get(() -> {
                DynamicTableNameHolder.set("p_tenant_data_LEAKED");
                // 故意不清理！
                task1Done.countDown();
            }));
            task1Done.await(5, TimeUnit.SECONDS);

            // 任务 2：用 TtlRunnable 包装，应该看不到任务 1 的残留值
            CountDownLatch task2Done = new CountDownLatch(1);
            pool.submit(TtlRunnable.get(() -> {
                String leaked = DynamicTableNameHolder.get();
                if (leaked != null) {
                    System.err.println("  [LEAK] 任务 2 看到了任务 1 的残留值: " + leaked);
                    errorCount.incrementAndGet();
                }
                task2Done.countDown();
            }));
            task2Done.await(5, TimeUnit.SECONDS);

            pool.shutdown();

            assertCondition(errorCount.get() == 0,
                    "TtlRunnable 应隔离上一个任务的 TTL 残留值");
        });

        test("线程池 + 嵌套 executeWithRoute — TTL 正确传递和清理", () -> {
            ExecutorService pool = Executors.newFixedThreadPool(4);
            int taskCount = 40;
            CountDownLatch doneLatch = new CountDownLatch(taskCount);
            AtomicInteger errorCount = new AtomicInteger(0);

            for (int i = 0; i < taskCount; i++) {
                final int idx = i;
                pool.submit(TtlRunnable.get(() -> {
                    try {
                        // 阶段 1：buildCondition（包含 share 表的嵌套 executeWithRoute）
                        PermissionCondition cond = buildCondition(300000 + idx, "lead", (long) (5000 + idx));

                        String afterBuild = DynamicTableNameHolder.get();
                        if (afterBuild != null) {
                            errorCount.incrementAndGet();
                            return;
                        }

                        // 阶段 2：业务数据查询
                        String bizTable = "p_tenant_data_" + (idx % 2000);
                        DynamicTableNameHolder.executeWith(bizTable, () -> {
                            String current = DynamicTableNameHolder.get();
                            if (!bizTable.equals(current)) {
                                errorCount.incrementAndGet();
                            }
                            cond.applyTo();
                            return null;
                        });

                        if (DynamicTableNameHolder.get() != null) {
                            errorCount.incrementAndGet();
                        }
                    } finally {
                        doneLatch.countDown();
                    }
                }));
            }

            boolean completed = doneLatch.await(30, TimeUnit.SECONDS);
            pool.shutdown();

            assertCondition(completed, "所有任务应在 30 秒内完成");
            assertCondition(errorCount.get() == 0,
                    "线程池嵌套场景应无错误，实际错误数: " + errorCount.get());
        });

        test("对比：不用 TtlRunnable 包装 — 原生 ThreadLocal 会泄漏", () -> {
            // 这个测试验证如果不用 TTL 包装，线程池复用时确实会泄漏
            ExecutorService pool = Executors.newFixedThreadPool(1);
            AtomicBoolean leaked = new AtomicBoolean(false);

            // 任务 1：设置值但不清理
            CountDownLatch task1Done = new CountDownLatch(1);
            pool.submit(() -> {  // 注意：没有 TtlRunnable 包装
                DynamicTableNameHolder.set("p_tenant_data_LEAKED");
                task1Done.countDown();
            });
            task1Done.await(5, TimeUnit.SECONDS);

            // 任务 2：不用 TtlRunnable，直接提交
            CountDownLatch task2Done = new CountDownLatch(1);
            pool.submit(() -> {  // 注意：没有 TtlRunnable 包装
                String val = DynamicTableNameHolder.get();
                if (val != null) {
                    leaked.set(true); // 预期会泄漏
                }
                DynamicTableNameHolder.clear(); // 清理
                task2Done.countDown();
            });
            task2Done.await(5, TimeUnit.SECONDS);

            pool.shutdown();

            // 注意：这里用 TTL（InheritableThreadLocal 子类），
            // 在单线程池中复用线程时，如果不用 TtlRunnable 包装，值确实会残留
            // 这就是为什么必须使用 TtlRunnable/TtlExecutorService 的原因
            assertCondition(leaked.get(),
                    "不用 TtlRunnable 包装时，线程池复用确实会导致 TTL 值泄漏（对照组验证通过）");
        });

        // ═══════════════════════════════════════════════════════════
        // 结果汇总
        // ═══════════════════════════════════════════════════════════

        System.out.println("\n══════════════════════════════════════════════════");
        System.out.println("  结果: " + passed + " passed, " + failed + " failed");
        System.out.println("══════════════════════════════════════════════════");

        if (!errors.isEmpty()) {
            System.out.println("\n❌ 失败详情:");
            for (String err : errors) {
                System.out.println("  - " + err);
            }
        }

        System.exit(failed > 0 ? 1 : 0);
    }
}
