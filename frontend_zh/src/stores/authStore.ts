/**
 * Zustand store for authentication state (Simplified version for notebook).
 */

import { create } from "zustand";
import { User, Session } from "@supabase/supabase-js";
import { supabase, isSupabaseConfigured } from "../lib/supabase";

interface AuthState {
  user: User | null;
  session: Session | null;
  loading: boolean;
  
  setSession: (session: Session | null) => void;
  signOut: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  session: null,
  loading: true,

  setSession: (session) => {
    set({
      session,
      user: session?.user ?? null,
      loading: false,
    });
  },

  signOut: async () => {
    if (!isSupabaseConfigured()) {
      set({ user: null, session: null, loading: false });
      return;
    }

    set({ loading: true });
    const { error } = await supabase.auth.signOut();
    
    if (error) {
      console.error('Sign out error:', error);
    }

    set({
      user: null,
      session: null,
      loading: false,
    });
  },
}));

/**
 * Get the current access token for API calls.
 */
export function getAccessToken(): string | null {
  return useAuthStore.getState().session?.access_token ?? null;
}
