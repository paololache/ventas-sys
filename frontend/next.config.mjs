/** @type {import('next').NextConfig} */
// "standalone" sólo para Docker; Vercel hace su propio empaquetado
const nextConfig = process.env.VERCEL ? {} : { output: "standalone" };
export default nextConfig;
