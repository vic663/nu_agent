import { Link } from "react-router-dom";
import logo from "./assets/logo.svg";
import { REPO_URL } from "./NavBar";

// Site footer (named NavBar2 to mirror the reference layout).
const NavBar2 = () => {
  const linkClass = "flex items-center text-brand-700 hover:text-brand-500 text-[16px]";

  return (
    <footer className="bg-brand-50 p-6 font-serif_title shadow-lg border-t border-brand-100">
      <div className="max-w-6xl mx-auto grid grid-cols-1 md:grid-cols-4 gap-6 items-start">
        <div className="flex justify-center md:justify-start">
          <Link to="/">
            <img src={logo} className="w-24" alt="NuAgent logo" />
          </Link>
        </div>

        <div>
          <h1 className="text-[18px] text-brand-700 mb-2">NuAgent</h1>
          <p className="font-lato text-[14px] text-stone-600 mb-2">
            An agentic V&amp;V workflow for convective heat-transfer and transport simulations.
          </p>
          <div className="flex items-center text-brand-700 text-[16px]">
            <i className="fa-regular fa-copyright mr-1"></i>
            <span>2026 Baihua Ren. MIT License.</span>
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <a href={REPO_URL} target="_blank" rel="noopener noreferrer" className={linkClass}>
            <i className="fa-brands fa-github text-[20px] w-[24px] mr-2"></i>
            GitHub
          </a>
          <a href={`${REPO_URL}/tree/main/docs`} target="_blank" rel="noopener noreferrer" className={linkClass}>
            <i className="fa-solid fa-book text-[20px] w-[24px] mr-2"></i>
            Documentation
          </a>
          <a href={`${REPO_URL}/blob/main/CHANGELOG.md`} target="_blank" rel="noopener noreferrer" className={linkClass}>
            <i className="fa-solid fa-clock-rotate-left text-[20px] w-[24px] mr-2"></i>
            Changelog
          </a>
        </div>

        <div className="flex flex-col gap-2">
          <a href={`${REPO_URL}/issues`} target="_blank" rel="noopener noreferrer" className={linkClass}>
            <i className="fa-solid fa-circle-question text-[20px] w-[24px] mr-2"></i>
            Issues
          </a>
          <a href={`${REPO_URL}/blob/main/CITATION.cff`} target="_blank" rel="noopener noreferrer" className={linkClass}>
            <i className="fa-solid fa-quote-left text-[20px] w-[24px] mr-2"></i>
            Cite NuAgent
          </a>
          <a href={`${REPO_URL}/actions`} target="_blank" rel="noopener noreferrer" className={linkClass}>
            <i className="fa-solid fa-circle-check text-[20px] w-[24px] mr-2"></i>
            CI status
          </a>
        </div>
      </div>
    </footer>
  );
};

export default NavBar2;
