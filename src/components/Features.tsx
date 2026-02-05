import { Shield, Zap, Globe, Cpu, Smartphone, Lock } from 'lucide-react';

const features = [
    {
        icon: <Zap className="w-8 h-8 text-primary" />,
        title: "Precision Scoring",
        description: "GOP (Goodness of Pronunciation) scores calculated using industrial-grade Kaldi acoustic models."
    },
    {
        icon: <Shield className="w-8 h-8 text-secondary" />,
        title: "AI Teacher",
        description: "Personalized feedback from GPT-4o, diagnosing specific phonetic errors and suggesting improvements."
    },
    {
        icon: <Globe className="w-8 h-8 text-primary" />,
        title: "Analysis Visualization",
        description: "Detailed F0 intonation curves, fluency pace charts, and ghost words detection."
    },
    {
        icon: <Cpu className="w-8 h-8 text-secondary" />,
        title: "Local & Cloud",
        description: "Run locally via Docker for privacy, or connect to cloud LLM APIs for advanced coaching."
    },
    {
        icon: <Smartphone className="w-8 h-8 text-primary" />,
        title: "Interactive Reports",
        description: "Generate beautiful, shareable HTML reports with embedded audio and interactive charts."
    },
    {
        icon: <Lock className="w-8 h-8 text-secondary" />,
        title: "Multi-Engine Support",
        description: "Automatically falls back to rule-based scoring if the deep learning engine is unavailable."
    }
];

export default function Features() {
    return (
        <section className="py-24 bg-background relative overflow-hidden">
            {/* Background Grid */}
            <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.02)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.02)_1px,transparent_1px)] bg-[size:60px_60px] [background-position:center] pointer-events-none"></div>

            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10">
                <div className="text-center mb-16">
                    <h2 className="text-sm font-bold tracking-widest text-secondary uppercase mb-4">Features</h2>
                    <h3 className="text-4xl md:text-5xl font-bold text-white mb-6">Designed for <span className="text-transparent bg-clip-text bg-gradient-to-r from-primary to-secondary">Excellence</span></h3>
                    <p className="text-gray-400 max-w-2xl mx-auto text-lg">
                        Everything you need to master English pronunciation.
                        From phoneme-level diagnosis to fluency training.
                    </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
                    {features.map((feature, index) => (
                        <div key={index} className="group p-8 rounded-2xl bg-white/5 border border-white/10 hover:border-primary/30 hover:bg-white/10 transition-all duration-300 hover:-translate-y-1 relative overflow-hidden">
                            <div className="absolute top-0 right-0 p-4 opacity-5 group-hover:opacity-10 transition-opacity">
                                {feature.icon}
                            </div>
                            <div className="bg-white/5 w-16 h-16 rounded-xl flex items-center justify-center mb-6 group-hover:scale-110 transition-transform duration-300 ring-1 ring-white/10 group-hover:ring-primary/50">
                                {feature.icon}
                            </div>
                            <h4 className="text-xl font-bold text-white mb-3">{feature.title}</h4>
                            <p className="text-gray-400 leading-relaxed">{feature.description}</p>
                        </div>
                    ))}
                </div>
            </div>
        </section>
    );
}
