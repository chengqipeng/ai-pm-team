/**
 * PageLayout — 页面布局组件
 *
 * 对齐老项目 layoutCmps/neoPage 的模式
 * 提供标准的 CRM 页面布局：侧边栏 + 顶栏 + 内容区
 *
 * 对齐 apps-ingage-web 的 base/components/home 布局结构
 */

export interface PageLayoutProps {
  /** 侧边栏内容 */
  sidebar?: React.ReactNode
  /** 顶栏内容 */
  topbar?: React.ReactNode
  /** 主内容区 */
  children: React.ReactNode
  /** 侧边栏宽度 */
  sidebarWidth?: number
}

export default function PageLayout({ sidebar, topbar, children, sidebarWidth = 224 }: PageLayoutProps) {
  return (
    <div className="flex h-screen bg-gray-50/80">
      {/* 侧边栏 */}
      {sidebar && (
        <aside className="fixed left-0 top-0 bottom-0 bg-white border-r border-gray-200/80 flex flex-col z-20"
          style={{ width: sidebarWidth }}>
          {sidebar}
        </aside>
      )}

      {/* 主区域 */}
      <div className="flex-1 flex flex-col h-screen" style={{ marginLeft: sidebar ? sidebarWidth : 0 }}>
        {/* 顶栏 */}
        {topbar && (
          <header className="h-14 bg-white border-b border-gray-200/80 flex items-center justify-between px-5 shrink-0">
            {topbar}
          </header>
        )}

        {/* 内容区 */}
        <main className="flex-1 min-h-0 overflow-auto">
          {children}
        </main>
      </div>
    </div>
  )
}
