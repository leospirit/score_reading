import { useState, useEffect, useRef } from 'react';
import { History, Search, Calendar, ExternalLink, Loader2, AlertCircle, TrendingUp, Trash2 } from 'lucide-react';

interface Report {
    id: string;
    url: string;
    timestamp: number;
    student_name: string;
    score?: number;
    status?: string;
}

export default function HistoryPage() {
    const [reports, setReports] = useState<Report[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [searchTerm, setSearchTerm] = useState("");

    // State for Jobs
    const [jobs, setJobs] = useState<any[]>([]);
    // Polling ref
    const pollInterval = useRef<any>(null);

    useEffect(() => {
        fetchData();
        // Start polling if there are active jobs
        startPolling();
        return () => stopPolling();
    }, []);

    const fetchData = async () => {
        setIsLoading(true);
        setError(null);
        try {
            await Promise.all([
                fetchReports().catch(e => console.error("Report fetch failed", e)),
                fetchJobs().catch(e => console.error("Job fetch failed", e))
            ]);
        } catch (err: any) {
            setError(err.message);
        } finally {
            setIsLoading(false);
        }
    };

    const fetchReports = async () => {
        const response = await fetch('http://localhost:8000/api/reports');
        if (!response.ok) throw new Error('Failed to fetch reports');
        const data = await response.json();
        setReports(data);
    };

    const fetchJobs = async () => {
        try {
            const response = await fetch('http://localhost:8000/api/jobs');
            if (response.ok) {
                const data = await response.json();
                // Filter for active jobs (queued or processing)
                // Also can keep completed ones if they aren't in reports yet, but report list is source of truth for completion.
                // We mainly rely on report list for completed.
                // But there is a race where job is completed but report scan hasn't picked it up (though unlikely if scanning dir).
                // Let's filter for queued/processing.
                setJobs(data);

                // Check if we need to continue polling
                const hasActive = data.some((j: any) => j.status === 'queued' || j.status === 'processing');
                if (hasActive) {
                    startPolling();
                } else {
                    stopPolling();
                }
            }
        } catch (e) {
            console.error("Failed to fetch jobs", e);
        }
    };

    const startPolling = () => {
        if (pollInterval.current) return;
        pollInterval.current = setInterval(async () => {
            // Background refresh
            await Promise.all([
                fetch('http://localhost:8000/api/reports').then(r => r.json()).then(d => setReports(d)),
                fetch('http://localhost:8000/api/jobs').then(r => r.json()).then(d => {
                    setJobs(d);
                    const hasActive = d.some((j: any) => j.status === 'queued' || j.status === 'processing');
                    if (!hasActive) stopPolling();
                })
            ]);
        }, 3000); // 3 seconds
    };

    const stopPolling = () => {
        if (pollInterval.current) {
            clearInterval(pollInterval.current);
            pollInterval.current = null;
        }
    };

    // Merge Reports and Jobs for display
    // Logic: 
    // 1. Create a map of active jobs by submission_id
    // 2. Filter out jobs that are already in reports (completed)
    // 3. Combine list

    // We treat "Job" as a potential "Report" locally for display
    const mergedList = [...reports];

    jobs.forEach(job => {
        // If job status is COMPLETED, it *should* be in reports. If not yet, we can optionally show it as "Finalizing..."
        // Or if status is QUEUED/PROCESSING, definitely show.
        // We use submission_id to dedupe. Job.submission_id vs Report.id

        const exists = reports.some(r => r.id === job.submission_id);
        if (!exists && (job.status === 'queued' || job.status === 'processing')) {
            // Mock a report object for display
            mergedList.unshift({
                id: job.submission_id,
                url: '#', // No link yet
                timestamp: job.timestamp,
                student_name: job.student_id, // Or parse from filename/id
                score: undefined, // Signal for Spinner
                status: job.status, // Custom field for our UI
                job_id: job.id
            } as any);
        }
    });

    // Sort again because we inserted at top but timestamps might vary
    mergedList.sort((a, b) => b.timestamp - a.timestamp);


    const filteredReports = mergedList.filter(r =>
        r.student_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        r.id.toLowerCase().includes(searchTerm.toLowerCase())
    );

    const formatTimestamp = (ts: number) => {
        return new Date(ts * 1000).toLocaleString();
    };

    // Helper for level text
    const getLevelInfo = (score?: number, status?: string) => {
        if (status === 'queued') return { label: 'Queued', color: 'text-gray-400', borderColor: 'border-gray-600' };
        if (status === 'processing') return { label: 'Analyzing...', color: 'text-blue-400', borderColor: 'border-blue-500' };

        if (!score) return { label: 'Pending', color: 'text-gray-500', borderColor: 'border-gray-700' };
        if (score >= 90) return { label: 'Native Like', color: 'text-purple-400', borderColor: 'border-purple-500' };
        if (score >= 80) return { label: 'Advanced', color: 'text-green-400', borderColor: 'border-green-500' };
        if (score >= 60) return { label: 'Intermediate', color: 'text-yellow-400', borderColor: 'border-yellow-500' };
        return { label: 'Beginner', color: 'text-red-400', borderColor: 'border-red-500' };
    };

    // Client-side pagination
    const [currentPage, setCurrentPage] = useState(1);
    const itemsPerPage = 8;
    const totalPages = Math.ceil(filteredReports.length / itemsPerPage);
    const paginatedReports = filteredReports.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage);

    const CircularScore = ({ score, status }: { score?: number, status?: string }) => {
        if (status === 'queued' || status === 'processing') {
            return (
                <div className="relative w-16 h-16 flex items-center justify-center">
                    <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
                </div>
            );
        }

        const radius = 24;
        const circumference = 2 * Math.PI * radius;
        // Use 0 if score is undefined, null, or NaN
        const safeScore = (score && !isNaN(score)) ? score : 0;
        const offset = circumference - (safeScore / 100) * circumference;
        const { color } = getLevelInfo(safeScore);

        return (
            <div className="relative w-16 h-16 flex items-center justify-center">
                <svg className="w-full h-full transform -rotate-90">
                    <circle cx="32" cy="32" r={radius} stroke="currentColor" strokeWidth="4" fill="transparent" className="text-white/10" />
                    <circle
                        cx="32" cy="32" r={radius}
                        stroke="currentColor" strokeWidth="4"
                        fill="transparent"
                        strokeDasharray={circumference}
                        strokeDashoffset={offset}
                        strokeLinecap="round"
                        className={`${color} transition-all duration-1000 ease-out`}
                    />
                </svg>
                <div className="absolute inset-0 flex items-center justify-center">
                    <span className={`text-sm font-bold ${color}`}>
                        {/* Only show numeric if score > 0, else -- */}
                        {safeScore > 0 ? Math.round(safeScore) + "%" : "--"}
                    </span>
                </div>
            </div>
        );
    };

    // Batch Selection Logic
    const [isSelectionMode, setIsSelectionMode] = useState(false);
    const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

    // Read Status Logic (Client-side)
    const [readReportIds, setReadReportIds] = useState<Set<string>>(() => {
        try {
            const saved = localStorage.getItem('readReportIds');
            return saved ? new Set(JSON.parse(saved)) : new Set();
        } catch (e) {
            return new Set();
        }
    });

    const markAsRead = (id: string) => {
        if (!readReportIds.has(id)) {
            const newSet = new Set(readReportIds);
            newSet.add(id);
            setReadReportIds(newSet);
            localStorage.setItem('readReportIds', JSON.stringify(Array.from(newSet)));
        }
    };

    const handleToggleSelect = (id: string) => {
        if (!isSelectionMode) return;
        const newSelected = new Set(selectedIds);
        if (newSelected.has(id)) {
            newSelected.delete(id);
        } else {
            newSelected.add(id);
        }
        setSelectedIds(newSelected);
    };

    const handleSelectAll = () => {
        if (selectedIds.size === filteredReports.length && filteredReports.length > 0) {
            setSelectedIds(new Set());
        } else {
            setSelectedIds(new Set(filteredReports.map(r => r.id)));
        }
    };

    const handleBatchDelete = async () => {
        if (selectedIds.size === 0) return;

        if (!window.confirm(`确定要删除选中的 ${selectedIds.size} 条记录吗？此操作无法撤销。`)) {
            return;
        }

        try {
            const response = await fetch('http://localhost:8000/api/reports/batch-delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ids: Array.from(selectedIds) })
            });

            if (response.ok) {
                setReports(prev => prev.filter(r => !selectedIds.has(r.id)));
                setSelectedIds(new Set());
                setIsSelectionMode(false); // Exit mode after delete
            } else {
                alert('批量删除失败，请重试');
            }
        } catch (err) {
            console.error(err);
            alert('批量删除出错');
        }
    };

    // Rescore Function
    const handleRescore = async (id: string) => {
        if (!window.confirm('Do you want to re-evaluate this recording with Gemini 3? This will create a new entry with "_new01" suffix.')) {
            return;
        }

        try {
            // OPTIMISTIC UPDATE or just background refresh. 
            // Do NOT set global loading state to avoid UI flash/freeze.

            const response = await fetch(`http://localhost:8000/api/jobs/${id}/rescore`, {
                method: 'POST'
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'Rescore failed');
            }

            // Success
            alert('Re-evaluation started! The new report will appear in the list shortly.');

            // Trigger immediate job fetch to see the new queued item
            fetchJobs();
            // Ensure polling is active
            startPolling();

        } catch (err: any) {
            console.error(err);
            alert(`Error: ${err.message}`);
        }
    };

    return (
        <div className="pt-24 pb-20 px-8 max-w-7xl mx-auto min-h-screen">
            {/* Header Section */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-8">
                <div>
                    <h1 className="text-3xl font-black text-white flex items-center gap-3">
                        <History className="w-8 h-8 text-primary" />
                        My Recording List
                    </h1>
                    <p className="text-gray-500 text-sm mt-1 ml-11">Manage and review your student assessments.</p>
                </div>

                <div className="flex items-center gap-4 w-full md:w-auto">
                    {/* Mode Toggle & Batch Actions */}
                    {isSelectionMode ? (
                        <div className="flex items-center gap-2 animate-in fade-in slide-in-from-right-4 duration-300">
                            <button
                                onClick={() => {
                                    setIsSelectionMode(false);
                                    setSelectedIds(new Set());
                                }}
                                className="text-gray-400 hover:text-white px-3 py-2 text-sm font-medium transition-colors"
                            >
                                Cancel
                            </button>
                            {selectedIds.size > 0 && (
                                <button
                                    onClick={handleBatchDelete}
                                    className="bg-red-500 text-white px-4 py-2.5 rounded-lg text-sm font-bold flex items-center gap-2 hover:bg-red-600 transition-all shadow-lg shadow-red-500/20"
                                >
                                    <Trash2 className="w-4 h-4" />
                                    Delete ({selectedIds.size})
                                </button>
                            )}
                        </div>
                    ) : (
                        <button
                            onClick={() => setIsSelectionMode(true)}
                            className="bg-white/5 border border-white/10 text-gray-300 px-4 py-2.5 rounded-lg text-sm font-bold flex items-center gap-2 hover:bg-white/10 hover:text-white transition-all"
                        >
                            <span className="w-4 h-4 border-2 border-current rounded-sm border-dashed"></span>
                            Select
                        </button>
                    )}

                    <div className="relative group max-w-xs w-full">
                        <div className="absolute inset-y-0 left-3 flex items-center pointer-events-none">
                            <Search className="w-4 h-4 text-gray-500" />
                        </div>
                        <input
                            type="text"
                            placeholder="Search recordings..."
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                            className="w-full bg-[#1e1e24] border border-white/5 rounded-lg py-2.5 pl-9 pr-4 text-sm text-gray-300 focus:outline-none focus:border-primary/50 transition-all font-medium"
                        />
                    </div>
                </div>
            </div>

            {/* List Content */}
            {isLoading ? (
                <div className="flex flex-col items-center justify-center py-32 space-y-4">
                    <Loader2 className="w-10 h-10 text-primary animate-spin opacity-50" />
                    <p className="text-gray-500 text-sm font-medium tracking-wide">LOADING RECORDS...</p>
                </div>
            ) : error ? (
                <div className="bg-red-500/10 border border-red-500/20 rounded-2xl p-8 flex flex-col items-center gap-4 text-center">
                    <AlertCircle className="w-10 h-10 text-red-400" />
                    <div>
                        <h3 className="text-lg font-bold text-white">Failed to load history</h3>
                        <p className="text-red-400/80 text-sm mt-1">{error}</p>
                    </div>
                    <button
                        onClick={fetchReports}
                        className="bg-red-500 text-white px-4 py-2 rounded-lg text-sm font-bold hover:bg-red-600 transition-colors"
                    >
                        Retry
                    </button>
                </div>
            ) : filteredReports.length === 0 ? (
                <div className="bg-[#1e1e24] border border-white/5 border-dashed rounded-2xl py-20 text-center">
                    <div className="bg-white/5 w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4">
                        <History className="w-8 h-8 text-gray-600" />
                    </div>
                    <h3 className="text-xl font-bold text-gray-300">No recordings found</h3>
                    <p className="text-gray-500 text-sm mt-2">Upload a new file to get started.</p>
                </div>
            ) : (
                <div className="bg-[#1e1e24] border border-white/5 rounded-2xl overflow-hidden shadow-2xl">
                    {/* Toolbar */}
                    {isSelectionMode && (
                        <div className="px-6 py-4 border-b border-white/5 flex items-center gap-4 bg-white/5 animate-in fade-in slide-in-from-top-2 duration-200">
                            <div className="flex items-center gap-3">
                                <input
                                    type="checkbox"
                                    checked={filteredReports.length > 0 && selectedIds.size === filteredReports.length}
                                    onChange={handleSelectAll}
                                    className="w-5 h-5 rounded border-gray-600 bg-gray-700 text-primary focus:ring-primary focus:ring-offset-gray-900 cursor-pointer"
                                />
                                <span className="text-sm font-bold text-gray-400">Select All</span>
                            </div>
                            <div className="text-xs text-gray-500 border-l border-white/10 pl-4">
                                {selectedIds.size} selected
                            </div>
                        </div>
                    )}

                    <div className="divide-y divide-white/5">
                        {paginatedReports.map((report) => {
                            const { label, color } = getLevelInfo(report.score);
                            const isSelected = selectedIds.has(report.id);
                            const isRead = readReportIds.has(report.id);

                            return (
                                <div
                                    key={report.id}
                                    className={`p-6 flex items-center gap-6 transition-colors group ${isSelected ? 'bg-primary/5' : 'hover:bg-white/[0.02]'} ${isSelectionMode ? 'cursor-pointer' : ''}`}
                                    onClick={() => isSelectionMode && handleToggleSelect(report.id)}
                                >
                                    {/* Checkbox (Conditional) */}
                                    {isSelectionMode && (
                                        <div className="shrink-0 animate-in fade-in zoom-in duration-200">
                                            <input
                                                type="checkbox"
                                                checked={isSelected}
                                                onChange={() => handleToggleSelect(report.id)}
                                                className="w-5 h-5 rounded border-gray-600 bg-gray-700 text-primary focus:ring-primary focus:ring-offset-gray-900 cursor-pointer pointer-events-none" // pointer-events-none to let parent click handle it
                                            />
                                        </div>
                                    )}

                                    {/* Status Dot (Unread Indicator) */}
                                    <div className="w-2.5 h-2.5 shrink-0 flex items-center justify-center">
                                        {!isRead && (
                                            <div className="w-2.5 h-2.5 rounded-full bg-green-500 shadow-[0_0_10px_rgba(34,197,94,0.5)] animate-pulse" title="Unread" />
                                        )}
                                    </div>

                                    {/* Main Info */}
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 mb-1">
                                            <h3 className={`text-lg transition-colors cursor-pointer ${isRead ? 'text-gray-400 font-medium' : 'text-white font-bold'} group-hover:text-primary`} onClick={() => {
                                                if (!isSelectionMode) {
                                                    markAsRead(report.id);
                                                    window.open(`http://localhost:8000${report.url}`, '_blank');
                                                }
                                            }}>
                                                {report.student_name}
                                            </h3>
                                            {!isSelectionMode && (
                                                <button className="text-gray-600 hover:text-gray-400 opacity-0 group-hover:opacity-100 transition-opacity">
                                                    <ExternalLink className="w-3.5 h-3.5" />
                                                </button>
                                            )}
                                        </div>
                                        <div className="flex items-center gap-4 text-xs text-gray-500 font-mono">
                                            <span className="flex items-center gap-1.5">
                                                <Calendar className="w-3.5 h-3.5" />
                                                {formatTimestamp(report.timestamp)}
                                            </span>
                                            <span className="w-1 h-1 bg-gray-700 rounded-full" />
                                            <span>ID: {report.id.substring(0, 8)}...</span>
                                        </div>
                                    </div>

                                    {/* Score & Level */}
                                    <div className="flex items-center gap-4 w-48 shrink-0 justify-end">
                                        <div className="text-right hidden sm:block">
                                            <div className={`text-sm font-bold ${color}`}>{label}</div>
                                            <div className="text-[10px] text-gray-600 uppercase tracking-wider font-bold">Proficiency</div>
                                        </div>
                                        <CircularScore score={report.score} />
                                    </div>

                                    {/* Actions (Only visible when NOT in selection mode) */}
                                    {!isSelectionMode && (
                                        <div className="flex items-center gap-2 pl-4 border-l border-white/5 ml-2" onClick={(e) => e.stopPropagation()}>
                                            <button
                                                onClick={() => {
                                                    markAsRead(report.id);
                                                    window.open(`http://localhost:8000${report.url}`, '_blank');
                                                }}
                                                className="p-2 text-gray-400 hover:text-white hover:bg-white/10 rounded-lg transition-all"
                                                title="View Report"
                                            >
                                                <TrendingUp className="w-4 h-4" />
                                            </button>

                                            {/* Rescore (Clone & Re-run) */}
                                            <button
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    handleRescore(report.id);
                                                }}
                                                className="p-2 text-gray-600 hover:text-blue-400 hover:bg-blue-500/10 rounded-lg transition-all"
                                                title="Rescore (Clone & Rerun)"
                                            >
                                                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="lucide lucide-refresh-cw"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" /><path d="M21 3v5h-5" /><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" /><path d="M3 21v-5h5" /></svg>
                                            </button>

                                            {/* Print / Export PDF */}
                                            <button
                                                onClick={() => {
                                                    markAsRead(report.id);
                                                    window.open(`http://localhost:8000${report.url}`, '_blank');
                                                }}
                                                className="p-2 text-gray-600 hover:text-primary hover:bg-primary/10 rounded-lg transition-all"
                                                title="Print / Export PDF"
                                            >
                                                {/* Use Printer Icon */}
                                                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="lucide lucide-printer"><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" /><path d="M6 9V3a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v6" /><rect x="6" y="14" width="12" height="8" rx="1" /></svg>
                                            </button>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>

                    {/* Pagination Footer */}
                    <div className="px-6 py-4 border-t border-white/5 flex items-center justify-between bg-black/20">

                        <div className="text-xs text-gray-500 font-medium">
                            Showing <span className="text-gray-300">{Math.min(filteredReports.length, (currentPage - 1) * itemsPerPage + 1)}</span> to <span className="text-gray-300">{Math.min(filteredReports.length, currentPage * itemsPerPage)}</span> of <span className="text-gray-300">{filteredReports.length}</span> entries
                        </div>
                        <div className="flex items-center gap-2">
                            <button
                                onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                                disabled={currentPage === 1}
                                className="px-3 py-1.5 text-xs font-bold text-gray-400 bg-white/5 rounded-lg hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                            >
                                Previous
                            </button>
                            <span className="text-xs font-mono text-gray-500 px-2">
                                Page {currentPage} / {totalPages || 1}
                            </span>
                            <button
                                onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                                disabled={currentPage === totalPages}
                                className="px-3 py-1.5 text-xs font-bold text-gray-400 bg-white/5 rounded-lg hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                            >
                                Next
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
