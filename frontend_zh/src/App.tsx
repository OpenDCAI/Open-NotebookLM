import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import Dashboard from './pages/Dashboard';
import NotebookView from './pages/NotebookView';
import { useAuthStore } from './stores/authStore';
import { supabase, isSupabaseConfigured } from './lib/supabase';

const pageVariants = {
  initial: (direction: number) => ({
    x: direction > 0 ? 20 : -20,
    opacity: 0,
  }),
  animate: {
    x: 0,
    opacity: 1,
    transition: { type: 'spring', stiffness: 300, damping: 30 },
  },
  exit: (direction: number) => ({
    x: direction > 0 ? -20 : 20,
    opacity: 0,
    transition: { duration: 0.2 },
  }),
};

function App() {
  const [currentView, setCurrentView] = useState<'dashboard' | 'notebook'>('dashboard');
  const [selectedNotebook, setSelectedNotebook] = useState<any>(null);
  const [dashboardRefresh, setDashboardRefresh] = useState(0);
  const [direction, setDirection] = useState(0);
  const { setSession } = useAuthStore();

  // Initialize auth session
  useEffect(() => {
    if (!isSupabaseConfigured()) {
      // 不做用户管理：使用 default，数据从 outputs 取
      const mockUser = {
        id: 'default',
        email: 'default',
        created_at: new Date().toISOString(),
        app_metadata: {},
        user_metadata: {},
        aud: 'authenticated',
        role: 'authenticated'
      };

      const mockSession = {
        access_token: 'mock-token',
        refresh_token: 'mock-refresh',
        expires_in: 3600,
        token_type: 'bearer',
        user: mockUser as any
      };

      setSession(mockSession as any);
      return;
    }

    // Get initial session
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session);
    });

    // Listen for auth changes
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session);
    });

    return () => subscription.unsubscribe();
  }, [setSession]);

  const handleOpenNotebook = (notebook: any) => {
    setSelectedNotebook(notebook);
    setDirection(1);
    setCurrentView('notebook');
  };

  const handleBackToDashboard = () => {
    setDirection(-1);
    setCurrentView('dashboard');
    setSelectedNotebook(null);
    setDashboardRefresh((n) => n + 1);
  };

  return (
    <div className="min-h-screen bg-[#f2f2f7]">
      <AnimatePresence mode="wait" custom={direction}>
        {currentView === 'dashboard' ? (
          <motion.div
            key="dashboard"
            custom={direction}
            variants={pageVariants}
            initial="initial"
            animate="animate"
            exit="exit"
          >
            <Dashboard onOpenNotebook={handleOpenNotebook} refreshTrigger={dashboardRefresh} />
          </motion.div>
        ) : (
          <motion.div
            key="notebook"
            custom={direction}
            variants={pageVariants}
            initial="initial"
            animate="animate"
            exit="exit"
          >
            <NotebookView
              notebook={selectedNotebook}
              onBack={handleBackToDashboard}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default App;
