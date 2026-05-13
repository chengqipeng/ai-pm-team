/**
 * Skill 管理应用入口
 */
import React, { useState } from 'react';
import { ConfigProvider, Layout, Typography } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { SkillList } from './SkillList';
import { SkillForm } from './SkillForm';

const { Header, Content } = Layout;

type Page = { type: 'list' } | { type: 'create' } | { type: 'edit'; apiKey: string };

const App: React.FC = () => {
  const [page, setPage] = useState<Page>({ type: 'list' });

  const renderPage = () => {
    switch (page.type) {
      case 'list':
        return (
          <SkillList
            onCreate={() => setPage({ type: 'create' })}
            onEdit={(apiKey) => setPage({ type: 'edit', apiKey })}
          />
        );
      case 'create':
        return (
          <SkillForm
            onBack={() => setPage({ type: 'list' })}
            onSaved={() => setPage({ type: 'list' })}
          />
        );
      case 'edit':
        return (
          <SkillForm
            apiKey={page.apiKey}
            onBack={() => setPage({ type: 'list' })}
            onSaved={() => setPage({ type: 'list' })}
          />
        );
    }
  };

  return (
    <ConfigProvider locale={zhCN}>
      <Layout style={{ minHeight: '100vh' }}>
        <Header style={{ background: '#fff', borderBottom: '1px solid #f0f0f0', padding: '0 24px' }}>
          <Typography.Title level={4} style={{ margin: '16px 0' }}>
            🛠️ 技能管理
          </Typography.Title>
        </Header>
        <Content style={{ background: '#f5f5f5' }}>
          {renderPage()}
        </Content>
      </Layout>
    </ConfigProvider>
  );
};

export default App;
