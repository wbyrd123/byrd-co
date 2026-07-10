import React from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import Auth from "@/pages/Auth";
import DashboardLayout from "@/pages/DashboardLayout";
import Overview from "@/pages/Overview";
import Campaigns from "@/pages/Campaigns";
import CampaignDetail from "@/pages/CampaignDetail";
import CreateCampaign from "@/pages/CreateCampaign";
import AdCopyStudio from "@/pages/AdCopyStudio";
import KeywordLab from "@/pages/KeywordLab";
import Analytics from "@/pages/Analytics";

const Protected = ({ children }) => {
  const { user, ready } = useAuth();
  if (!ready) return null;
  if (!user) return <Navigate to="/auth" replace />;
  return children;
};

function App() {
  return (
    <div className="App">
      <AuthProvider>
        <BrowserRouter>
          <Toaster
            position="bottom-right"
            toastOptions={{
              style: {
                borderRadius: 0,
                border: "2px solid #111",
                boxShadow: "4px 4px 0 0 #111",
                fontFamily: "IBM Plex Mono, monospace",
                background: "#fff",
                color: "#111",
              },
            }}
          />
          <Routes>
            <Route path="/auth" element={<Auth />} />
            <Route
              path="/"
              element={
                <Protected>
                  <DashboardLayout />
                </Protected>
              }
            >
              <Route index element={<Overview />} />
              <Route path="campaigns" element={<Campaigns />} />
              <Route path="campaigns/new" element={<CreateCampaign />} />
              <Route path="campaigns/:id" element={<CampaignDetail />} />
              <Route path="ad-copy" element={<AdCopyStudio />} />
              <Route path="keywords" element={<KeywordLab />} />
              <Route path="analytics" element={<Analytics />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </div>
  );
}

export default App;
