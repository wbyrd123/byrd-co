import React from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider, useAuth } from "@/context/AuthContext";

// Byrd & CO pages
import Home from "@/byrd/Home";
import PortalLogin from "@/byrd/PortalLogin";
import PortalInvite from "@/byrd/PortalInvite";
import ClientPortal from "@/byrd/ClientPortal";
import AdminLayout from "@/byrd/AdminLayout";
import AdminDashboard from "@/byrd/AdminDashboard";
import AdminClients from "@/byrd/AdminClients";
import AdminClientDetail from "@/byrd/AdminClientDetail";
import AdminQuotes from "@/byrd/AdminQuotes";
import AdminScenarios from "@/byrd/AdminScenarios";
import AdminScenarioDetail from "@/byrd/AdminScenarioDetail";
import AdminLenders from "@/byrd/AdminLenders";
import AdminGuide from "@/byrd/AdminGuide";
import AdminTestimonials from "@/byrd/AdminTestimonials";
import AdminAssistant from "@/byrd/AdminAssistant";
import AdminContacts from "@/byrd/AdminContacts";
import Unsubscribe from "@/byrd/Unsubscribe";
import FeeAgreementSign from "@/byrd/FeeAgreementSign";
import LenderView from "@/byrd/LenderView";
import LendersApplyPage from "@/byrd/LendersApplyPage";
import LenderActivate from "@/byrd/LenderActivate";
import LenderPortal from "@/byrd/LenderPortal";

// AdsCopilot (staff-only)
import DashboardLayout from "@/pages/DashboardLayout";
import Overview from "@/pages/Overview";
import Campaigns from "@/pages/Campaigns";
import CampaignDetail from "@/pages/CampaignDetail";
import CreateCampaign from "@/pages/CreateCampaign";
import AdCopyStudio from "@/pages/AdCopyStudio";
import KeywordLab from "@/pages/KeywordLab";
import Analytics from "@/pages/Analytics";

const RequireAuth = ({ children, role }) => {
  const { user, ready } = useAuth();
  if (!ready) return null;
  if (!user) return <Navigate to="/portal/login" replace />;
  if (role && user.role !== role) {
    // Route to the correct home based on role
    const home = user.role === "admin" ? "/admin"
               : user.role === "lender" ? "/lender/portal"
               : "/portal";
    return <Navigate to={home} replace />;
  }
  return children;
};

const AdsCopilotWrapper = () => (
  <div className="adscopilot-scope">
    <DashboardLayout />
  </div>
);

function App() {
  return (
    <div className="App">
      <AuthProvider>
        <BrowserRouter>
          <Toaster
            position="top-right"
            richColors
            toastOptions={{
              style: {
                fontFamily: "Inter, sans-serif",
              },
            }}
          />
          <Routes>
            {/* Public marketing */}
            <Route path="/" element={<Home />} />

            {/* Portal auth */}
            <Route path="/portal/login" element={<PortalLogin />} />
            <Route path="/portal/invite/:token" element={<PortalInvite />} />

            {/* Public lender view (token-gated) */}
            <Route path="/lender/scenario/:token" element={<LenderView />} />
            <Route path="/lenders/apply" element={<LendersApplyPage />} />
            <Route path="/lender/activate/:token" element={<LenderActivate />} />
            <Route path="/unsubscribe" element={<Unsubscribe />} />
            <Route path="/fee-agreement/:token" element={<FeeAgreementSign />} />

            {/* Lender portal (role=lender) */}
            <Route
              path="/lender/portal"
              element={
                <RequireAuth role="lender">
                  <LenderPortal />
                </RequireAuth>
              }
            />

            {/* Client portal (role=client) */}
            <Route
              path="/portal"
              element={
                <RequireAuth role="client">
                  <ClientPortal />
                </RequireAuth>
              }
            />

            {/* Admin portal (role=admin) */}
            <Route
              path="/admin"
              element={
                <RequireAuth role="admin">
                  <AdminLayout />
                </RequireAuth>
              }
            >
              <Route index element={<AdminDashboard />} />
              <Route path="clients" element={<AdminClients />} />
              <Route path="clients/:id" element={<AdminClientDetail />} />
              <Route path="quotes" element={<AdminQuotes />} />
              <Route path="scenarios" element={<AdminScenarios />} />
              <Route path="scenarios/:id" element={<AdminScenarioDetail />} />
              <Route path="lenders" element={<AdminLenders />} />
              <Route path="testimonials" element={<AdminTestimonials />} />
              <Route path="assistant" element={<AdminAssistant />} />
              <Route path="contacts" element={<AdminContacts />} />
              <Route path="guide" element={<AdminGuide />} />
            </Route>

            {/* AdsCopilot (admin only) */}
            <Route
              path="/adscopilot"
              element={
                <RequireAuth role="admin">
                  <AdsCopilotWrapper />
                </RequireAuth>
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
