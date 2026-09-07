import { useState } from "react";
import { Link, NavLink } from "react-router-dom";
import logo from "./assets/logo.svg";

export const REPO_URL = "https://github.com/vic663/nuagent";

const links = [
  { to: "/", label: "Home" },
  { to: "/About", label: "About" },
  { to: "/Capabilities", label: "Capabilities" },
  { to: "/Results", label: "Results" },
  { to: "/GetStarted", label: "Get Started" },
  { to: "/Contact", label: "Contact" },
];

const NavBar = () => {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

  const closeMobileMenu = () => setIsMobileMenuOpen(false);

  const desktopLinkClass = ({ isActive }) =>
    `p-2 text-xl transition-colors hover:text-brand-900 ${
      isActive ? "text-brand-900 border-b-2 border-accent-500" : "text-brand-700"
    }`;

  return (
    <>
      <header className="sticky top-0 z-40 flex justify-center shadow-lg bg-brand-50/95 backdrop-blur font-serif_title">
        <div className="w-full max-w-6xl px-4 py-2">
          <div className="flex items-center justify-between">
            <Link to="/" className="flex items-center" onClick={closeMobileMenu}>
              <img src={logo} className="w-12 md:w-14" alt="NuAgent logo" />
              <div className="ml-4">
                <h1 className="text-2xl md:text-4xl text-brand-700 leading-none">NuAgent</h1>
                <p className="hidden md:block font-lato text-xs text-stone-500 mt-1">
                  Verified, validated and calibrated simulations, driven by a qualifiable agent
                </p>
              </div>
            </Link>

            <div className="md:hidden">
              <button
                onClick={() => setIsMobileMenuOpen(true)}
                className="p-2"
                aria-label="Open menu"
              >
                <i className="text-3xl fa-solid fa-bars text-brand-800"></i>
              </button>
            </div>
          </div>

          <nav className="hidden md:flex justify-end items-center mt-1">
            {links.map((l) => (
              <NavLink key={l.to} to={l.to} end={l.to === "/"} className={desktopLinkClass}>
                {l.label}
              </NavLink>
            ))}
            <a
              href={REPO_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="p-2 text-xl text-brand-700 hover:text-brand-900"
              aria-label="GitHub repository"
            >
              <i className="fa-brands fa-github"></i>
            </a>
          </nav>
        </div>
      </header>

      {isMobileMenuOpen && (
        <div className="fixed inset-0 z-50 flex flex-col items-center justify-center space-y-8 bg-brand-950 text-brand-200 font-serif_title">
          <button
            onClick={closeMobileMenu}
            className="absolute top-4 right-4 p-2"
            aria-label="Close menu"
          >
            <i className="text-4xl fa-solid fa-square-xmark text-brand-300"></i>
          </button>

          {links.map((l) => (
            <Link
              key={l.to}
              to={l.to}
              onClick={closeMobileMenu}
              className="text-3xl font-bold hover:text-white"
            >
              {l.label}
            </Link>
          ))}
          <a
            href={REPO_URL}
            target="_blank"
            rel="noopener noreferrer"
            onClick={closeMobileMenu}
            className="text-3xl font-bold hover:text-white"
          >
            <i className="fa-brands fa-github mr-3"></i>GitHub
          </a>
        </div>
      )}
    </>
  );
};

export default NavBar;
