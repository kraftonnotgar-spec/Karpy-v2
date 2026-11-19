import { THEME_POLICY_STORAGE_KEY, THEME_STORAGE_KEY } from "@/core/lib/theme-policy";

// Runs before first paint so the stored or system theme never flashes. Uses the same storage
// keys and resolution rules as preferences.tsx / theme-policy.ts.
export const themeScript = `(function(){try{var t=null,p={default_theme:"light",theme_mode:"both"};try{t=localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});var c=JSON.parse(localStorage.getItem(${JSON.stringify(THEME_POLICY_STORAGE_KEY)}));if(c&&["light","dark"].includes(c.default_theme)&&["both","light","dark"].includes(c.theme_mode))p=c}catch(e){}var v=p.theme_mode!=="both"?p.theme_mode:t==="light"||t==="dark"?t:t==="system"?(window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"):p.default_theme;document.documentElement.classList.toggle("dark",v==="dark")}catch(e){}})()`;
