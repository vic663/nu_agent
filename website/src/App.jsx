import { BrowserRouter, Routes, Route } from "react-router-dom";
import NavBar from "./NavBar";
import NavBar2 from "./NavBar2";
import ScrollToTop from "./ScrollToTop";
import HomePage from "./HomePage";
import PageAbout from "./PageAbout";
import PageCapabilities from "./PageCapabilities";
import PageResults from "./PageResults";
import PageGetStarted from "./PageGetStarted";
import PageContact from "./PageContact";

// Vite's BASE_URL is "/" for local dev and Vercel, and "/nu_agent/" for the GitHub Pages build
// (`npm run build:pages`). React Router wants it without the trailing slash.
const basename = import.meta.env.BASE_URL.replace(/\/$/, "");

export default function App() {
  return (
    <BrowserRouter basename={basename}>
      <ScrollToTop />
      <div className="min-h-screen flex flex-col">
        <NavBar />
        <main className="flex-1">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/About" element={<PageAbout />} />
            <Route path="/Capabilities" element={<PageCapabilities />} />
            <Route path="/Results" element={<PageResults />} />
            <Route path="/GetStarted" element={<PageGetStarted />} />
            <Route path="/Contact" element={<PageContact />} />
            <Route path="*" element={<HomePage />} />
          </Routes>
        </main>
        <NavBar2 />
      </div>
    </BrowserRouter>
  );
}
