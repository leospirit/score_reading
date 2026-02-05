import React, { useState, useEffect } from 'react';

interface SettingsModalProps {
    isOpen: boolean;
    onClose: () => void;
}

interface GeminiConfig {
    api_key: string;
    model: string;
    has_key: boolean;
}

interface AzureConfig {
    api_key: string;
    region: string;
    has_key: boolean;
}

interface ConfigState {
    provider: string;
    base_url: string;
    model: string;
    api_key: string;
    has_key: boolean;
    gemini: GeminiConfig;
    azure: AzureConfig;
}

const SettingsModal: React.FC<SettingsModalProps> = ({ isOpen, onClose }) => {
    const [loading, setLoading] = useState(false);
    const [config, setConfig] = useState<ConfigState>({
        provider: 'openai',
        base_url: '',
        model: 'gpt-4o',
        api_key: '',
        has_key: false,
        gemini: { api_key: '', model: 'gemini-1.5-flash', has_key: false },
        azure: { api_key: '', region: 'eastus', has_key: false },
    });

    const API_HOST = "http://localhost:8000";

    useEffect(() => {
        if (isOpen) {
            fetchConfig();
        }
    }, [isOpen]);

    const fetchConfig = async () => {
        setLoading(true);
        try {
            const res = await fetch(`${API_HOST}/api/config`);
            if (res.ok) {
                const data = await res.json();
                setConfig({
                    provider: data.llm.provider,
                    base_url: data.llm.base_url || '',
                    model: data.llm.model,
                    has_key: data.llm.has_key,
                    api_key: '',
                    gemini: {
                        api_key: '',
                        model: data.gemini.model,
                        has_key: data.gemini.has_key
                    },
                    azure: {
                        api_key: '',
                        region: data.azure.region,
                        has_key: data.azure.has_key
                    }
                });
            }
        } catch (error) {
            console.error("Failed to fetch config", error);
        } finally {
            setLoading(false);
        }
    };

    const handleSave = async () => {
        setLoading(true);
        try {
            const payload = {
                llm: {
                    provider: config.provider,
                    base_url: config.base_url,
                    model: config.model,
                    api_key: config.api_key || undefined
                },
                gemini: {
                    api_key: config.gemini.api_key || undefined,
                    model: config.gemini.model
                },
                azure: {
                    api_key: config.azure.api_key || undefined,
                    region: config.azure.region
                }
            };

            const res = await fetch(`${API_HOST}/api/config`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (res.ok) {
                onClose();
                alert("Configuration saved!");
            } else {
                alert("Failed to save configuration.");
            }
        } catch (error) {
            console.error("Failed to save config", error);
            alert("Error saving configuration.");
        } finally {
            setLoading(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 overflow-y-auto">
            <div className="bg-[#1e1e24] w-full max-w-md my-8 p-6 rounded-2xl shadow-xl border border-white/10 text-white">
                <div className="flex justify-between items-center mb-6">
                    <h2 className="text-xl font-bold">Settings</h2>
                    <button onClick={onClose} className="text-gray-400 hover:text-white">✕</button>
                </div>

                <div className="space-y-6 max-h-[70vh] overflow-y-auto pr-2 scrollbar-hide">
                    {/* Section: Advisor AI */}
                    <div className="space-y-4">
                        <div className="flex items-center justify-between">
                            <h3 className="text-sm font-bold text-blue-400 uppercase tracking-wider">Advisor AI (Feedback)</h3>
                            <span className="text-[10px] bg-blue-500/10 text-blue-400 px-2 py-0.5 rounded border border-blue-500/20">OpenAI Compatible</span>
                        </div>

                        <div>
                            <label className="block text-xs font-medium text-gray-400 mb-1">Provider Preset</label>
                            <select
                                value={config.provider}
                                onChange={e => {
                                    const p = e.target.value;
                                    let updates: any = { provider: p };

                                    // Auto-fill presets
                                    if (p === 'zhipu') {
                                        updates.base_url = "https://open.bigmodel.cn/api/paas/v4/";
                                        updates.model = "glm-4";
                                    } else if (p === 'deepseek') {
                                        updates.base_url = "https://api.deepseek.com/v1";
                                        updates.model = "deepseek-chat";
                                    } else if (p === 'moonshot') {
                                        updates.base_url = "https://api.moonshot.cn/v1";
                                        updates.model = "moonshot-v1-8k";
                                    } else if (p === 'qwen') {
                                        updates.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1";
                                        updates.model = "qwen-plus";
                                    } else if (p === 'openai') {
                                        updates.base_url = "";
                                        updates.model = "gpt-4o";
                                    }

                                    setConfig({ ...config, ...updates });
                                }}
                                className="w-full bg-black/20 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                            >
                                <option value="openai">OpenAI (Default)</option>
                                <option value="zhipu">Zhipu AI (智谱 GLM-4)</option>
                                <option value="qwen">Qwen (通义千问)</option>
                                <option value="deepseek">DeepSeek (深度求索)</option>
                                <option value="moonshot">Moonshot (Kimi / Windows)</option>
                                <option value="custom">Custom (Any OpenAI Compatible)</option>
                            </select>
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <label className="block text-xs font-medium text-gray-400 mb-1">Model Name</label>
                                <input
                                    type="text"
                                    value={config.model}
                                    onChange={e => setConfig({ ...config, model: e.target.value })}
                                    placeholder="e.g. gpt-4o, glm-4"
                                    className="w-full bg-black/20 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                                />
                            </div>
                            <div>
                                <label className="block text-xs font-medium text-gray-400 mb-1">Base URL (Optional)</label>
                                <input
                                    type="text"
                                    value={config.base_url}
                                    onChange={e => setConfig({ ...config, base_url: e.target.value })}
                                    placeholder="https://api.openai.com/v1"
                                    className="w-full bg-black/20 border border-white/10 rounded-lg px-3 py-2 text-sm text-gray-300 focus:outline-none focus:border-blue-500 font-mono text-xs"
                                />
                            </div>
                        </div>

                        <div>
                            <label className="block text-xs font-medium text-gray-400 mb-1">
                                API Key {config.has_key && <span className="text-green-500">(Configured)</span>}
                                <span className="block text-[10px] text-gray-500 font-normal mt-0.5">
                                    Supports multiple keys separated by comma for fallback/rotation.
                                </span>
                            </label>
                            <input
                                type="password"
                                value={config.api_key}
                                onChange={e => setConfig({ ...config, api_key: e.target.value })}
                                placeholder={config.has_key ? "Keep existing key" : "sk-key1,sk-key2..."}
                                className="w-full bg-black/20 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                            />
                        </div>
                    </div>

                    <hr className="border-white/5" />

                    {/* Section: Gemini Multimodal (Assessment) */}
                    <div className="space-y-4">
                        <h3 className="text-sm font-bold text-purple-400 uppercase tracking-wider">Gemini (Pro Assessment)</h3>
                        <div>
                            <label className="block text-xs font-medium text-gray-400 mb-1">
                                Gemini API Key {config.gemini.has_key && <span className="text-green-500">(Configured)</span>}
                                <span className="block text-[10px] text-gray-500 font-normal mt-0.5">
                                    Supports multiple keys (comma-separated).
                                </span>
                            </label>
                            <input
                                type="password"
                                value={config.gemini.api_key}
                                onChange={e => setConfig({ ...config, gemini: { ...config.gemini, api_key: e.target.value } })}
                                placeholder={config.gemini.has_key ? "Keep existing key" : "key1,key2..."}
                                className="w-full bg-black/20 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                            />
                        </div>
                        <div>
                            <label className="block text-xs font-medium text-gray-400 mb-1">Model</label>
                            <select
                                value={config.gemini.model}
                                onChange={e => setConfig({ ...config, gemini: { ...config.gemini, model: e.target.value } })}
                                className="w-full bg-black/20 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                            >
                                <option value="gemini-3-flash-preview">Gemini 3 Flash Preview (Latest Speed)</option>
                                <option value="gemini-3-pro-preview">Gemini 3 Pro Preview (Latest Intelligence)</option>
                                <option value="gemini-1.5-pro">Gemini 1.5 Pro (Recommended)</option>
                                <option value="gemini-1.5-flash">Gemini 1.5 Flash (Fast)</option>
                            </select>
                        </div>
                    </div>

                    <hr className="border-white/5" />

                    {/* Section: Azure (Optional) */}
                    <div className="space-y-4">
                        <h3 className="text-sm font-bold text-gray-400 uppercase tracking-wider">Azure (Cloud Assessment)</h3>
                        <div>
                            <label className="block text-xs font-medium text-gray-400 mb-1">Azure API Key {config.azure.has_key && <span className="text-green-500">(Configured)</span>}</label>
                            <input
                                type="password"
                                value={config.azure.api_key}
                                onChange={e => setConfig({ ...config, azure: { ...config.azure, api_key: e.target.value } })}
                                placeholder={config.azure.has_key ? "Keep existing key" : "Key"}
                                className="w-full bg-black/20 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                            />
                        </div>
                    </div>

                    <hr className="border-white/5" />

                    {/* Section: Performance Settings */}
                    <div className="space-y-4">
                        <h3 className="text-sm font-bold text-green-400 uppercase tracking-wider">Performance (Queue)</h3>
                        <div>
                            <label className="block text-xs font-medium text-gray-400 mb-1">
                                Max Concurrency: <span className="text-white font-bold">{localStorage.getItem("concurrency_limit") || 2}</span>
                            </label>
                            <input
                                type="range"
                                min="1"
                                max="10"
                                step="1"
                                defaultValue={localStorage.getItem("concurrency_limit") || 2}
                                onChange={(e) => {
                                    localStorage.setItem("concurrency_limit", e.target.value);
                                    const span = e.target.previousElementSibling?.querySelector('span');
                                    if (span) span.textContent = e.target.value;
                                }}
                                className="w-full h-2 bg-white/10 rounded-lg appearance-none cursor-pointer accent-green-500"
                            />
                            <p className="text-[10px] text-gray-500 mt-1">
                                Higher values utilize more resources but may hit API rate limits. Default: 2.
                            </p>
                        </div>
                    </div>
                </div>

                <div className="mt-8 flex justify-end gap-3">
                    <button
                        onClick={onClose}
                        className="px-4 py-2 rounded-lg text-gray-300 hover:bg-white/5 transition-colors"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={handleSave}
                        disabled={loading}
                        className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-medium transition-colors disabled:opacity-50"
                    >
                        {loading ? 'Saving...' : 'Save Changes'}
                    </button>
                </div>
            </div>
        </div>
    );
};

export default SettingsModal;
