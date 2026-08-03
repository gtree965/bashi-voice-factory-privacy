/**
 * Bashi Voice Factory Privacy Edition - JavaScript Application
 * Bilingual local Qwen3-TTS interface with offline STT helpers.
 */

// State Management
const state = {
    currentAppTab: 'tts', // 'tts' or 'stt'
    sttModels: [],
    speakerDiarization: null,
    selectedSttModel: '',
    sttFile: null,
    sttJobId: null,
    currentLang: 'en',
    selectedVoice: 'uncle_fu',
    selectedCategory: 'all',
    selectedStylePreset: 'standard_reading',
    customInstruct: '',
    currentPreviewAudio: null,
    systemInfo: null,
    cudaUpgrade: null,
    cudaUpgradeInProgress: false,
    benchmark: null,
    benchmarkInProgress: false,
    estimateTimer: null,
    eta: null,
    voices: null,
    currentAudioUrl: null,
    // Sentence playback state
    playbackMode: 'single', // 'single' or 'sentence'
    sentences: [],
    sentenceTotal: 0,  // authoritative total from SSE; drives progress bar
    currentSentenceIndex: 0,
    isPlaying: false,
    isPaused: false,  // NEW: track paused state for toggle
    pauseDuration: 2, // seconds between sentences
    synthesisAbort: null,
    synthesisComplete: true,
    synthesisStopped: false,
    retryAfterStop: false,
    runToken: 0,
    waitingForNextChunk: false,
    autoPlayFirstChunk: true,
    // Long-form preview playback is intentionally isolated from sentence mode.
    longChunks: [],
    longChunkIndex: 0,
    longPreviewPlaying: false,
    longPreviewWaiting: false,
    longPreviewMuted: false,
    longChunkArrivalTimes: [],
    lastGroupSeconds: null, // Cross-run telemetry for honest restart-wait guidance.
    longPreviewStrategyDecided: false,
    longPreviewBufferTarget: 0,
    longPreviewGiveUp: false,
    longTotal: 0,
    longFinalAudioReady: false,
    // NEW: Chunking settings
    chunkingEnabled: true,
    maxWords: 15,  // Default: Medium (15 words)
    newlineHard: true  // treat every newline as a boundary (line-by-line mode)
};

// DOM Elements
const elements = {
    textInput: document.getElementById('text-input'),
    voiceTabs: document.getElementById('voice-tabs'),
    voiceGrid: document.getElementById('voice-grid'),
    stylePresetGrid: document.getElementById('style-preset-grid'),
    styleInstructHint: document.getElementById('style-instruct-hint'),
    styleInstructText: document.getElementById('style-instruct-text'),
    customInstructGroup: document.getElementById('custom-instruct-group'),
    customInstructInput: document.getElementById('custom-instruct-input'),
    backendChip: document.getElementById('backend-chip'),
    backendChipLabel: document.getElementById('backend-chip-label'),
    backendDetail: document.getElementById('backend-detail'),
    benchmarkBtn: document.getElementById('benchmark-btn'),
    benchmarkReferencePanel: document.getElementById('benchmark-reference-panel'),
    firstRunBanner: document.getElementById('first-run-banner'),
    firstRunBenchmarkBtn: document.getElementById('first-run-benchmark-btn'),
    firstRunDismissBtn: document.getElementById('first-run-dismiss-btn'),
    cudaUpgradeBanner: document.getElementById('cuda-upgrade-banner'),
    cudaUpgradeText: document.getElementById('cuda-upgrade-text'),
    cudaUpgradeBtn: document.getElementById('cuda-upgrade-btn'),
    cudaUpgradeProgress: document.getElementById('cuda-upgrade-progress'),
    cudaUpgradeProgressFill: document.getElementById('cuda-upgrade-progress-fill'),
    cudaUpgradeProgressText: document.getElementById('cuda-upgrade-progress-text'),
    updateCheckBtn: document.getElementById('update-check-btn'),
    etaPanel: document.getElementById('eta-panel'),
    settingsSection: document.getElementById('settings-section'),
    generateBtn: document.getElementById('generate-btn'),
    generateBtnText: document.getElementById('generate-btn-text'),
    loading: document.getElementById('loading'),
    playerSection: document.getElementById('player-section'),
    audioPlayer: document.getElementById('audio-player'),
    downloadBtn: document.getElementById('download-btn'),
    pauseSlider: document.getElementById('pause-slider'),
    pauseValue: document.getElementById('pause-value'),
    charCount: document.querySelector('.char-count'),
    toast: document.getElementById('toast'),
    // Sentence playback elements
    sentencePlayerSection: document.getElementById('sentence-player-section'),
    sentenceList: document.getElementById('sentence-list'),
    sentenceAudio: document.getElementById('sentence-audio'),
    progressFill: document.getElementById('progress-fill'),
    sentenceProgress: document.getElementById('sentence-progress'),
    sentencePlaybackStatus: document.getElementById('sentence-playback-status'),
    longPreviewAudio: document.getElementById('long-preview-audio'),
    longPreviewStatus: document.getElementById('long-preview-status'),
    longPreviewToggle: document.getElementById('long-preview-toggle'),
    longStopBtn: document.getElementById('long-stop-btn'),
    sentenceStopBtn: document.getElementById('sentence-stop-btn'),
    autoplaySetting: document.getElementById('autoplay-setting'),
    autoplayFirstChunk: document.getElementById('autoplay-first-chunk'),
    pauseSetting: document.getElementById('pause-setting'),
    modeHint: document.getElementById('mode-hint'),
    fileInput: document.getElementById('file-input'),
    uploadBtn: document.getElementById('upload-btn'),
    dropZone: document.getElementById('drop-zone'),
    formatSelect: document.getElementById('format-select'),
    // App Tabs
    ttsContainer: document.getElementById('tts-container'),
    sttContainer: document.getElementById('stt-container'),
    // STT Elements
    sttFileInput: document.getElementById('stt-file-input'),
    sttUploadZone: document.getElementById('stt-upload-zone'),
    sttSelectedFile: document.getElementById('stt-selected-file'),
    sttFilenameDisplay: document.getElementById('stt-filename-display'),
    sttModelSelect: document.getElementById('stt-model-select'),
    sttDownloadBtn: document.getElementById('stt-download-btn'),
    sttModelProgress: document.getElementById('stt-model-progress'),
    sttSpeakerIdToggle: document.getElementById('stt-speaker-id-toggle'),
    sttSpeakerCountSelect: document.getElementById('stt-speaker-count-select'),
    sttSpeakerPresetSelect: document.getElementById('stt-speaker-preset-select'),
    sttSpeakerDownloadBtn: document.getElementById('stt-speaker-download-btn'),
    sttSpeakerStatus: document.getElementById('stt-speaker-status'),
    sttSpeakerModelProgress: document.getElementById('stt-speaker-model-progress'),
    sttTranscribeBtn: document.getElementById('stt-transcribe-btn'),
    sttLangSelect: document.getElementById('stt-lang-select'),
    sttJobProgress: document.getElementById('stt-job-progress'),
    sttLiveSegments: document.getElementById('stt-live-segments'),
    sttResultSection: document.getElementById('stt-result-section'),
    sttResultText: document.getElementById('stt-result-text'),
};

function setProgressAnim(element, enabled) {
    if (!element) return;
    element.classList.toggle('chunk-stream-anim', enabled);
}

function clearLongProgressAnim() {
    setProgressAnim(document.getElementById('long-progress-fill'), false);
}

function clearSentenceProgressAnim() {
    setProgressAnim(elements.progressFill, false);
}

const SINGLE_SYNTHESIS_LIMITS = {
    absoluteChars: 4000,
    cjkChars: 120,
    cjkSentences: 5,
    latinWords: 80,
    latinSentences: 6
};
const STYLE_PREVIEW_VERSION = 'native-language-v2';
const FIRST_RUN_STORAGE_KEY = 'bashi_first_run_completed';
const AUTOPLAY_FIRST_CHUNK_STORAGE_KEY = 'bashi_autoplay_first_chunk';
const RESTART_RETRY_BUDGET_MS = 60000;
const RESTART_RETRY_BASE_DELAY_MS = 250;
const RESTART_RETRY_MAX_DELAY_MS = 750;
const LONG_PREVIEW_GAP_MS = 350;

/**
 * Choose the one-time long-preview rebuffer target from
 * S ≥ i·t − (i−1)·d. `elapsed` is stable generation-equivalent time already
 * represented by arrived groups (the caller excludes first-group warm-up).
 * This is pure and exported so the browser console can exercise slow paths.
 */
function calculateLongPreviewBufferStrategy({ n, t, d, elapsed = 0 } = {}) {
    const total = Number(n);
    const generationSeconds = Number(t);
    const playbackSeconds = Number(d);
    const elapsedSeconds = Math.max(0, Number(elapsed) || 0);
    if (!(total > 0) || !(generationSeconds > 0) || !(playbackSeconds > 0)) {
        return { shouldStart: false, chunksNeeded: 1, giveUp: false };
    }

    const requiredBufferSeconds = generationSeconds <= playbackSeconds
        ? generationSeconds
        : total * generationSeconds - (total - 1) * playbackSeconds;
    const giveUp = requiredBufferSeconds > 0.8 * total * generationSeconds;
    const completedChunks = Math.min(
        total,
        Math.floor((elapsedSeconds / generationSeconds) + Number.EPSILON)
    );
    const additionalChunks = Math.ceil(
        Math.max(0, requiredBufferSeconds - elapsedSeconds) / generationSeconds
    );
    const chunksNeeded = Math.min(
        total,
        Math.max(1, completedChunks + additionalChunks)
    );

    return {
        shouldStart: !giveUp && completedChunks >= chunksNeeded,
        chunksNeeded,
        giveUp
    };
}

window.calculateLongPreviewBufferStrategy = calculateLongPreviewBufferStrategy;

const STYLE_PRESETS = [
    {
        id: 'standard_reading',
        labelEn: 'Standard Reading',
        labelZh: '标准朗读',
        summaryEn: 'Neutral, steady delivery',
        summaryZh: '正常语速，清晰平稳',
        instruct: '用标准正常语速说话，停顿自然，语气中性、清晰、平稳，适合作为默认朗读风格。\nSpeak at a normal, natural pace with clear pauses and a neutral, steady tone as the default reading style.',
        preview: true
    },
    {
        id: 'clear_slow_reading',
        labelEn: 'Clear Slow Reading',
        labelZh: '清晰慢读',
        summaryEn: 'Warm, clear, slower speech',
        summaryZh: '亲切清楚，稍慢易听',
        instruct: '用偏慢的语速说话，咬字饱满，停顿稍长，语气亲切清晰，确保每个字都听得清。\nSpeak at a moderately slow pace with full articulation and slightly longer pauses, in a warm and clear tone.',
        preview: true
    },
    {
        id: 'language_class',
        labelEn: 'Language Class',
        labelZh: '语言课带读',
        summaryEn: 'Very slow and articulated',
        summaryZh: '极慢，清楚带读',
        instruct: '用极慢的语速说话，像语言课老师带读句子，停顿延长，咬字清楚，节奏稳定，保持自然，不要拖沓或夸张。\nSpeak very slowly like a language teacher leading a sentence, with extended pauses and clear articulation; keep the rhythm steady and natural, not dragging.',
        preview: true
    },
    {
        id: 'briefing',
        labelEn: 'Briefing',
        labelZh: '简报播报',
        summaryEn: 'Slightly faster and compact',
        summaryZh: '稍快，紧凑清晰',
        instruct: '用比正常稍快的语速说话，表达紧凑，停顿略少，适合资讯简报和日常对话，必须清晰可懂。\nSpeak slightly faster than normal, with tighter phrasing and fewer pauses, suitable for briefings and conversation; remain clear.',
        preview: true
    },
    {
        id: 'classic_recitation',
        labelEn: 'Classic Reading',
        labelZh: '古文经典',
        summaryEn: 'Steady, calm classic reading',
        summaryZh: '沉稳平和的经典诵读',
        instruct: '用古文经典诵读的语速说话，节奏沉稳，停顿在标点处，语气平和端正，不要带明显情绪起伏。\nSpeak in a steady classic-reading pace with composed pauses at punctuation, in a calm and balanced tone.',
        preview: true
    },
    {
        id: 'custom',
        labelEn: 'Custom',
        labelZh: '自定义',
        summaryEn: 'Write an instruction',
        summaryZh: '自由输入控制指令',
        custom: true,
        instruct: ''
    }
];

const VOICE_CATEGORY_HINTS = {
    dylan: 'zh',
    eric: 'zh',
    ryan: 'en',
    aiden: 'en',
    ono_anna: 'ja',
    sohee: 'ko'
};

const SUPPORTED_LANGUAGE_TABS = [
    { id: 'all', category_en: 'All speakers', category_zh: '全部音色' },
    { id: 'zh', category_en: 'Chinese', category_zh: '中文' },
    { id: 'en', category_en: 'English', category_zh: '英文' },
    { id: 'ja', category_en: 'Japanese', category_zh: '日语' },
    { id: 'ko', category_en: 'Korean', category_zh: '韩语' },
    { id: 'de', category_en: 'German', category_zh: '德语', crossLingual: true },
    { id: 'fr', category_en: 'French', category_zh: '法语', crossLingual: true },
    { id: 'ru', category_en: 'Russian', category_zh: '俄语', crossLingual: true },
    { id: 'pt', category_en: 'Portuguese', category_zh: '葡萄牙语', crossLingual: true },
    { id: 'es', category_en: 'Spanish', category_zh: '西班牙语', crossLingual: true },
    { id: 'it', category_en: 'Italian', category_zh: '意大利语', crossLingual: true }
];

function shouldUseLongSynthesis(text) {
    const trimmed = text.trim();
    if (trimmed.length > SINGLE_SYNTHESIS_LIMITS.absoluteChars) {
        return true;
    }

    const cjkChars = (trimmed.match(/[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]/g) || []).length;
    const sentenceCount = (trimmed.match(/[.!?。！？।؟;]+/g) || []).length;
    const isMostlyCjk = cjkChars >= Math.max(12, trimmed.length * 0.25);

    // Medium-length CJK passages can hit backend generation caps in single-shot
    // mode, especially with slower speakers. Route them through sentence-level
    // long synthesis so the full text is generated and then merged.
    if (isMostlyCjk) {
        return cjkChars > SINGLE_SYNTHESIS_LIMITS.cjkChars
            || sentenceCount >= SINGLE_SYNTHESIS_LIMITS.cjkSentences;
    }

    const wordCount = trimmed.split(/\s+/).filter(Boolean).length;
    return wordCount > SINGLE_SYNTHESIS_LIMITS.latinWords
        || sentenceCount >= SINGLE_SYNTHESIS_LIMITS.latinSentences;
}

function getStylePreset(presetId = state.selectedStylePreset) {
    return STYLE_PRESETS.find(preset => preset.id === presetId) || STYLE_PRESETS[0];
}

function getVisibleStyleInstruct(preset = getStylePreset()) {
    if (!preset.custom) return preset.instruct || '';

    const value = (elements.customInstructInput?.value || '').trim();
    if (value) return value;

    return state.currentLang === 'zh'
        ? '自定义指令为空：当前不会向模型发送额外风格指令。'
        : 'Custom instruction is empty: no extra style instruction will be sent to the model.';
}

function updateStyleInstructionHint() {
    if (!elements.styleInstructHint || !elements.styleInstructText) return;

    const preset = getStylePreset();
    const text = getVisibleStyleInstruct(preset);
    elements.styleInstructHint.style.display = 'block';
    elements.styleInstructText.textContent = text;
}

function getStylePresetPreviewUrl(preset) {
    if (!preset.preview) return '';

    const speakerId = state.selectedVoice || 'uncle_fu';
    return `/static/audio/style_previews/${encodeURIComponent(speakerId)}/${preset.id}.mp3?v=${STYLE_PREVIEW_VERSION}`;
}

function renderStylePresets() {
    if (!elements.stylePresetGrid) return;

    elements.stylePresetGrid.innerHTML = STYLE_PRESETS.map(preset => {
        const isActive = preset.id === state.selectedStylePreset;
        const title = state.currentLang === 'zh' ? preset.labelZh : preset.labelEn;
        const summary = state.currentLang === 'zh' ? preset.summaryZh : preset.summaryEn;
        const previewLabel = state.currentLang === 'zh' ? '试听' : 'Preview';
        const previewTitle = state.currentLang === 'zh'
            ? `试听 ${title}`
            : `Preview ${title}`;
        const previewButton = preset.preview ? `
            <button class="style-preview-btn"
                    type="button"
                    data-preset-preview-id="${preset.id}"
                    aria-label="${escapeHtml(previewTitle)}"
                    title="${escapeHtml(previewTitle)}">
                <span aria-hidden="true">▶</span>
                <span>${escapeHtml(previewLabel)}</span>
            </button>
        ` : '';
        return `
            <div class="style-preset-card ${isActive ? 'active' : ''}">
                <button class="style-preset-btn"
                        type="button"
                        data-preset-id="${preset.id}">
                    <span class="style-preset-title">${escapeHtml(title)}</span>
                    <span class="style-preset-subtitle">${escapeHtml(summary)}</span>
                </button>
                ${previewButton}
            </div>
        `;
    }).join('');

    const preset = getStylePreset();
    if (elements.customInstructGroup) {
        elements.customInstructGroup.style.display = preset.custom ? 'flex' : 'none';
    }
    if (elements.customInstructInput) {
        elements.customInstructInput.placeholder = elements.customInstructInput.getAttribute(
            state.currentLang === 'zh' ? 'data-placeholder-zh' : 'data-placeholder-en'
        );
    }
    updateStyleInstructionHint();
}

function selectStylePreset(presetId) {
    const preset = getStylePreset(presetId);
    state.selectedStylePreset = preset.id;

    if (preset.voiceId && state.selectedVoice !== preset.voiceId) {
        state.selectedVoice = preset.voiceId;
        const preferredCategory = VOICE_CATEGORY_HINTS[preset.voiceId];
        if (preferredCategory && getVoiceCategoryData(preferredCategory)) {
            state.selectedCategory = preferredCategory;
            renderVoiceTabs();
            updateDemoButtons(preferredCategory);
        }
        renderVoices(state.selectedCategory);
    }

    renderStylePresets();
    scheduleEstimate({ includeReferences: true });
}

function playStylePresetPreview(presetId) {
    const preset = getStylePreset(presetId);
    const previewUrl = getStylePresetPreviewUrl(preset);
    if (!previewUrl) {
        showToast(
            state.currentLang === 'zh'
                ? '自定义指令没有固定试听音频'
                : 'Custom instructions do not have a fixed preview'
        );
        return;
    }

    if (state.currentPreviewAudio) {
        state.currentPreviewAudio.pause();
        state.currentPreviewAudio.currentTime = 0;
    }

    const audio = new Audio(previewUrl);
    state.currentPreviewAudio = audio;
    audio.addEventListener('error', () => {
        showToast(
            state.currentLang === 'zh'
                ? '当前音色的试听音频缺失'
                : 'Preview audio is missing for the current speaker'
        );
    }, { once: true });
    audio.play().catch(() => {
        showToast(
            state.currentLang === 'zh'
                ? '试听音频暂时无法播放'
                : 'Preview audio could not be played'
        );
    });
}

function buildInstruct() {
    const preset = getStylePreset();
    const parts = [];
    const presetInstruct = preset.custom
        ? (elements.customInstructInput?.value || '').trim()
        : preset.instruct;
    if (presetInstruct) {
        parts.push(presetInstruct);
    }
    return parts.join('\n');
}

function t(en, zh) {
    return state.currentLang === 'zh' ? zh : en;
}

function formatSeconds(seconds) {
    if (seconds == null || Number.isNaN(Number(seconds))) {
        return t('unknown', '未知');
    }
    const total = Math.max(0, Math.round(Number(seconds)));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    if (hours > 0) {
        return state.currentLang === 'zh'
            ? `${hours}小时${minutes}分${secs}秒`
            : `${hours}h ${minutes}m ${secs}s`;
    }
    if (minutes > 0) {
        return state.currentLang === 'zh'
            ? `${minutes}分${secs}秒`
            : `${minutes}m ${secs}s`;
    }
    return state.currentLang === 'zh' ? `${secs}秒` : `${secs}s`;
}

function getBenchmarkStorageKey() {
    const info = state.systemInfo || {};
    const backend = info.backend || 'unknown';
    const model = info.model_default || 'unknown-model';
    const device = info.gpu_device_identity || 'unknown-device';
    return `bashi_benchmark_v2:${backend}:${model}:${device}`;
}

function getCurrentSynthesisMode(text = elements.textInput?.value || '') {
    if (state.playbackMode === 'sentence') {
        return 'sentence';
    }
    return shouldUseLongSynthesis(text) ? 'long' : 'single';
}

function loadSavedBenchmark() {
    try {
        const raw = localStorage.getItem(getBenchmarkStorageKey());
        state.benchmark = raw ? JSON.parse(raw) : null;
    } catch (_) {
        state.benchmark = null;
    }
}

function saveBenchmark(benchmark) {
    state.benchmark = {
        ...benchmark,
        saved_at: new Date().toISOString()
    };
    localStorage.setItem(getBenchmarkStorageKey(), JSON.stringify(state.benchmark));
}

function completeFirstRun() {
    try {
        localStorage.setItem(FIRST_RUN_STORAGE_KEY, '1');
    } catch (_) {
        // Storage may be unavailable; still hide the banner for this page load.
    }
    if (elements.firstRunBanner) {
        elements.firstRunBanner.style.display = 'none';
    }
}

function renderFirstRunBanner() {
    if (!elements.firstRunBanner) return;

    let completed = false;
    try {
        completed = localStorage.getItem(FIRST_RUN_STORAGE_KEY) === '1';
    } catch (_) {
        completed = false;
    }
    elements.firstRunBanner.style.display = completed ? 'none' : 'flex';
}

function renderSystemInfo() {
    if (!elements.backendChip || !elements.backendChipLabel) return;

    const info = state.systemInfo;
    if (!info) {
        elements.backendChip.className = 'backend-chip loading';
        elements.backendChipLabel.textContent = t('Detecting backend...', '正在检测后端...');
        if (elements.backendDetail) elements.backendDetail.textContent = '';
        return;
    }

    elements.backendChip.className = `backend-chip ${info.chip_level === 'warning' ? 'warning' : ''}`;
    elements.backendChipLabel.textContent = state.currentLang === 'zh'
        ? info.friendly_label_zh
        : info.friendly_label_en;
    if (elements.backendDetail) {
        const detail = state.currentLang === 'zh' ? info.detail_zh : info.detail_en;
        const device = info.gpu_device_identity && info.gpu_device_identity !== 'unknown'
            ? ` · ${info.gpu_device_identity}`
            : '';
        elements.backendDetail.textContent = `${detail}${device}`;
    }
}

function renderBenchmarkReferencePanel(references = null) {
    if (!elements.benchmarkReferencePanel) return;

    if (state.benchmarkInProgress) {
        elements.benchmarkReferencePanel.innerHTML = escapeHtml(
            t('Warming the model, then timing a 25-character Chinese speed test. Please wait...', '正在预热模型，然后运行 25 字中文测速，请稍候...')
        );
        return;
    }

    if (!state.benchmark) {
        elements.benchmarkReferencePanel.innerHTML = escapeHtml(
            t('Run Speed Test to show rough 1000 / 5000-character wait times.', '点击“测速”后会显示 1000 / 5000 字的粗略等待时间。')
        );
        return;
    }

    const rows = [];
    rows.push(`<div><strong>${escapeHtml(t('Based on this warm speed test', '基于本次预热后测速'))}</strong>: ${escapeHtml(formatSeconds(state.benchmark.inference_seconds))} / ${state.benchmark.char_count} ${escapeHtml(t('Chinese chars', '中文字'))}</div>`);
    if (state.benchmark.warmup_excluded) {
        const warmupDetail = state.benchmark.warmup_seconds != null
            ? `: ${formatSeconds(state.benchmark.warmup_seconds)}`
            : '';
        rows.push(`<div>${escapeHtml(t('Model warm-up was excluded from this timing', '模型预热时间未计入本次测速'))}${escapeHtml(warmupDetail)}</div>`);
    }
    if (Array.isArray(references)) {
        references.forEach(row => {
            const estimate = row.estimate;
            if (!estimate?.mid) return;
            rows.push(`<div>${row.char_count.toLocaleString()} ${escapeHtml(t('chars reference', '字参考'))}: ${escapeHtml(estimate.low.display_zh && state.currentLang === 'zh' ? estimate.low.display_zh : formatSeconds(estimate.low.seconds))} - ${escapeHtml(estimate.high.display_zh && state.currentLang === 'zh' ? estimate.high.display_zh : formatSeconds(estimate.high.seconds))}</div>`);
        });
    }
    rows.push(`<div>${escapeHtml(t('Rough estimate; real runs may vary by about +/-30%.', '粗略估算；实际生成可能波动约 ±30%。'))}</div>`);
    elements.benchmarkReferencePanel.innerHTML = rows.join('');
}

async function loadSystemInfo() {
    renderSystemInfo();
    try {
        const response = await fetch('/api/system-info');
        const info = await response.json();
        state.systemInfo = info;
        loadSavedBenchmark();
        renderSystemInfo();
        renderBenchmarkReferencePanel();
        requestEstimate({ includeReferences: true });
    } catch (error) {
        console.error('Failed to load system info:', error);
        if (elements.backendChip) elements.backendChip.className = 'backend-chip warning';
        if (elements.backendChipLabel) {
            elements.backendChipLabel.textContent = t('Backend unknown', '后端未知');
        }
    }
}

function renderCudaUpgrade() {
    if (!elements.cudaUpgradeBanner) return;
    const info = state.cudaUpgrade;
    if (!info) {
        elements.cudaUpgradeBanner.style.display = 'none';
        return;
    }

    // Three terminal UI states:
    //   1. requires_restart === true  -> success banner with restart prompt
    //   2. applicable === true        -> blue banner with upgrade button
    //   3. otherwise                  -> hidden
    if (info.requires_restart) {
        elements.cudaUpgradeBanner.className = 'cuda-upgrade-banner success';
        elements.cudaUpgradeBanner.style.display = 'flex';
        elements.cudaUpgradeText.textContent = t(
            'CUDA runtime installed. Restart the app to enable CUDA acceleration.',
            'CUDA 运行时已安装。请重启应用以启用 CUDA 加速。'
        );
        if (elements.cudaUpgradeBtn) elements.cudaUpgradeBtn.style.display = 'none';
        if (elements.cudaUpgradeProgress) elements.cudaUpgradeProgress.style.display = 'none';
        return;
    }

    if (!info.applicable) {
        elements.cudaUpgradeBanner.style.display = 'none';
        return;
    }

    elements.cudaUpgradeBanner.className = 'cuda-upgrade-banner';
    elements.cudaUpgradeBanner.style.display = 'flex';
    elements.cudaUpgradeText.textContent = t(
        'NVIDIA GPU detected. Optional CUDA acceleration is available as a separate download (~600 MB).',
        '检测到 NVIDIA 显卡。可选 CUDA 加速运行时（约 600 MB）单独下载。'
    );
    if (elements.cudaUpgradeBtn) {
        elements.cudaUpgradeBtn.style.display = '';
        elements.cudaUpgradeBtn.disabled = state.cudaUpgradeInProgress;
        elements.cudaUpgradeBtn.textContent = state.cudaUpgradeInProgress
            ? t('Downloading...', '下载中...')
            : t('Upgrade to CUDA', '升级到 CUDA 加速');
    }
}

async function loadCudaUpgradeStatus() {
    if (!elements.cudaUpgradeBanner) return;
    try {
        const response = await fetch('/api/cuda-upgrade/status');
        if (!response.ok) {
            state.cudaUpgrade = null;
        } else {
            state.cudaUpgrade = await response.json();
        }
    } catch (error) {
        console.error('Failed to load CUDA upgrade status:', error);
        state.cudaUpgrade = null;
    }
    renderCudaUpgrade();
}

async function downloadCudaRuntime() {
    if (state.cudaUpgradeInProgress) return;
    if (!elements.cudaUpgradeProgress || !elements.cudaUpgradeProgressFill) return;

    state.cudaUpgradeInProgress = true;
    elements.cudaUpgradeBtn.disabled = true;
    elements.cudaUpgradeBtn.textContent = t('Downloading...', '下载中...');
    elements.cudaUpgradeProgress.style.display = 'block';
    elements.cudaUpgradeProgressFill.style.width = '0%';
    elements.cudaUpgradeProgressText.textContent = t('Starting...', '开始下载...');

    try {
        const response = await fetch('/api/cuda-upgrade/download', { method: 'POST' });
        if (!response.ok) {
            const errJson = await response.json().catch(() => ({}));
            throw new Error(errJson.error || `HTTP ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const dataStr = line.substring(6).trim();
                if (!dataStr) continue;
                const data = JSON.parse(dataStr);

                if (data.status === 'downloading') {
                    const pct = data.progress != null ? data.progress : 0;
                    elements.cudaUpgradeProgressFill.style.width = `${pct}%`;
                    let progressLine = state.currentLang === 'zh' && data.message_zh
                        ? data.message_zh
                        : (data.message || `Downloading ${data.file || ''}...`);
                    if (data.file_index != null && data.total_files != null && data.file_index > 0) {
                        progressLine += ` (${data.file_index}/${data.total_files})`;
                    }
                    elements.cudaUpgradeProgressText.textContent = progressLine;
                } else if (data.status === 'done') {
                    elements.cudaUpgradeProgressFill.style.width = '100%';
                    elements.cudaUpgradeProgressText.textContent = state.currentLang === 'zh'
                        ? (data.message_zh || 'CUDA 运行时已安装。')
                        : (data.message || 'CUDA runtime installed.');
                    await loadCudaUpgradeStatus();
                    return;
                } else if (data.status === 'error') {
                    throw new Error(data.error || 'Download failed');
                }
            }
        }
    } catch (error) {
        console.error('CUDA upgrade download failed:', error);
        const prefix = state.currentLang === 'zh' ? 'CUDA 下载失败' : 'CUDA download failed';
        if (typeof showToast === 'function') {
            showToast(`${prefix}: ${error.message}`, 'error');
        }
        if (elements.cudaUpgradeProgressText) {
            elements.cudaUpgradeProgressText.textContent = `${prefix}: ${error.message}`;
        }
    } finally {
        state.cudaUpgradeInProgress = false;
        if (elements.cudaUpgradeBtn) {
            elements.cudaUpgradeBtn.disabled = false;
            elements.cudaUpgradeBtn.textContent = t('Upgrade to CUDA', '升级到 CUDA 加速');
        }
    }
}

function setBenchmarkInProgress(active) {
    state.benchmarkInProgress = active;
    if (elements.benchmarkBtn) {
        elements.benchmarkBtn.disabled = active;
        elements.benchmarkBtn.textContent = active
            ? t('Testing...', '测速中...')
            : t('Speed Test', '测速');
    }
    if (elements.generateBtn) {
        elements.generateBtn.disabled = active;
    }
    renderBenchmarkReferencePanel();
}

async function runBenchmark() {
    if (state.benchmarkInProgress) return;

    setBenchmarkInProgress(true);
    try {
        const response = await fetch('/api/benchmark', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                voice: state.selectedVoice,
                instruct: buildInstruct()
            })
        });
        const result = await response.json();
        if (!response.ok || !result.success) {
            const fallback = response.status === 409
                ? t('The engine is busy. Try again after current generation finishes.', '引擎正在忙，请等当前生成结束后再试。')
                : response.status === 408
                    ? t('Speed test timed out. Try again later.', '测速超时，请稍后再试。')
                    : t('Speed test failed.', '测速失败。');
            throw new Error(result.error || fallback);
        }
        saveBenchmark(result);
        const benchmarkLabel = result.warmup_excluded
            ? t('Warm speed test done', '预热后测速完成')
            : t('Speed test done', '测速完成');
        showToast(
            `${benchmarkLabel}: ${formatSeconds(result.inference_seconds)}`,
            'success'
        );
        requestEstimate({ includeReferences: true });
    } catch (error) {
        console.error('Benchmark failed:', error);
        showToast(error.message || t('Speed test failed.', '测速失败。'), 'error');
    } finally {
        setBenchmarkInProgress(false);
    }
}

function scheduleEstimate(options = {}) {
    if (state.estimateTimer) {
        clearTimeout(state.estimateTimer);
    }
    state.estimateTimer = setTimeout(() => {
        requestEstimate(options);
    }, 350);
}

async function requestEstimate(options = {}) {
    if (!elements.textInput) return;
    try {
        const response = await fetch('/api/estimate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                text: elements.textInput.value || '',
                voice: state.selectedVoice,
                benchmark: state.benchmark,
                include_references: Boolean(options.includeReferences),
                synthesis_mode: getCurrentSynthesisMode(elements.textInput.value || '')
            })
        });
        const data = await response.json();
        if (!response.ok || !data.success) return;
        state.eta = data;
        renderEta(data);
        if (options.includeReferences) {
            renderBenchmarkReferencePanel(data.references);
        }
    } catch (error) {
        console.error('ETA estimate failed:', error);
    }
}

function renderEta(data = state.eta) {
    if (!elements.etaPanel || !data) return;

    const chars = data.char_count || 0;
    const warnings = [];
    if (!data.has_benchmark && chars > 500) {
        warnings.push(t('No speed test yet. Long text can take much longer than expected.', '尚未测速。长文本可能比预期等得更久。'));
    }
    if (data.is_cpu_mode && chars > 200) {
        warnings.push(t('CPU mode is much slower on long text, especially on the first run.', 'CPU 模式长文本会明显更慢，首次生成尤其如此。'));
    }

    if (chars === 0 && warnings.length === 0) {
        elements.etaPanel.style.display = 'none';
        return;
    }

    const chunks = data.chunk_count || 0;
    const hasGroupCount = data.group_count !== null && data.group_count !== undefined;
    const displayedCount = hasGroupCount ? data.group_count : chunks;
    const workUnit = data.synthesis_mode === 'single'
        ? t('single pass', '单次合成')
        : `${displayedCount} ${hasGroupCount ? t('groups', '组') : t('chunks', '段')}`;
    let html = '';
    if (data.estimate?.low && data.estimate?.high) {
        const low = state.currentLang === 'zh' ? data.estimate.low.display_zh : data.estimate.low.display_en;
        const high = state.currentLang === 'zh' ? data.estimate.high.display_zh : data.estimate.high.display_en;
        html = `<div><strong>${escapeHtml(t('Current text estimate', '当前文本预计'))}</strong>: ${escapeHtml(low)} - ${escapeHtml(high)} · ${chars.toLocaleString()} ${escapeHtml(t('chars', '字'))} · ${escapeHtml(workUnit)}</div>`;
        const estimateSourceText = state.benchmark?.warmup_excluded
            ? t('Based on warmed quick benchmark, rough range only.', '基于预热后的快速测速，仅为粗略范围。')
            : t('Based on quick benchmark, rough range only.', '基于快速测速，仅为粗略范围。');
        html += `<div>${escapeHtml(estimateSourceText)}</div>`;
    } else {
        html = `<div><strong>${escapeHtml(t('Current text', '当前文本'))}</strong>: ${chars.toLocaleString()} ${escapeHtml(t('chars', '字'))} · ${escapeHtml(workUnit)}</div>`;
    }

    warnings.forEach(warning => {
        html += `<div class="eta-warning">${escapeHtml(warning)}</div>`;
    });
    elements.etaPanel.innerHTML = html;
    elements.etaPanel.style.display = 'block';
}

// Demo texts for each language category
// Texts are chosen to produce 4-6 chunks in shadowing mode (Medium preset),
// and to clearly show different chunk counts across Short / Medium / Long presets.
const DEMO_TEXTS = {
    all: [
        { text: '你好！欢迎使用巴适声工厂。在跟读模式下，文本会被自动切分成短小片段，每个片段播放后会自动暂停，你可以随时重复任何片段来练习发音。', en: 'Chinese Demo', zh: '中文示例' },
        { text: 'Hello! Welcome to Bashi Voice Factory. In shadowing mode, your text is split into short chunks for easy repetition. Each chunk plays one by one, and you can repeat any chunk by clicking on it.', en: 'English Demo', zh: '英文示例' },
    ],
    en: [
        { text: 'Hello! Welcome to Bashi Voice Factory. In shadowing mode, your text is split into short chunks for easy repetition. Each chunk plays one by one, and you can repeat any chunk by clicking on it.', en: 'English Demo', zh: '英文示例' },
    ],
    zh: [
        { text: '你好！欢迎使用巴适声工厂。在跟读模式下，文本会被自动切分成短小片段，每个片段播放后会自动暂停，你可以随时重复任何片段来练习发音。', en: 'Chinese Demo', zh: '中文示例' },
    ],
    ja: [
        { text: 'こんにちは！Bashi Voice Factoryへようこそ。高品質なテキスト読み上げのデモンストレーションです。', en: 'Japanese Demo', zh: '日语示例' },
    ],
    ko: [
        { text: '안녕하세요! Bashi Voice Factory에 오신 것을 환영합니다. 고품질 텍스트 투 스피치의 데모입니다. 원하는 목소리를 선택하고, 속도와 음조 슬라이더를 자유롭게 조절하여 자신만의 완벽한 음성을 만들어 보세요.', en: 'Korean Demo', zh: '韩语示例' },
    ],
    de: [
        { text: 'Hallo! Willkommen im Bashi Voice Factory. Dies ist eine Demonstration hochwertiger Sprachsynthese. Wählen Sie eine Stimme, und passen Sie Geschwindigkeit und Tonhöhe für den perfekten Klang an.', en: 'German Demo', zh: '德语示例' },
    ],
    fr: [
        { text: 'Bonjour! Bienvenue dans Bashi Voice Factory. Ceci est une démonstration de synthèse vocale de haute qualité. Sélectionnez une voix, et ajustez la vitesse et la tonalité pour trouver les réglages parfaits.', en: 'French Demo', zh: '法语示例' },
    ],
    ru: [
        { text: 'Здравствуйте! Добро пожаловать в Bashi Voice Factory. Это демонстрация высококачественного синтеза речи. Выберите голос, и настройте скорость и высоту тона, чтобы найти идеальные параметры для себя.', en: 'Russian Demo', zh: '俄语示例' },
    ],
    pt: [
        { text: 'Olá! Bem-vindo ao Bashi Voice Factory. Esta é uma demonstração de síntese de fala de alta qualidade. Selecione qualquer voz, e ajuste a velocidade e o tom para encontrar as configurações perfeitas.', en: 'Portuguese Demo', zh: '葡萄牙语示例' },
    ],
    es: [
        { text: '¡Hola! Bienvenido a Bashi Voice Factory. Esta es una demostración de síntesis de voz de alta calidad. Selecciona una voz, y ajusta la velocidad y el tono para encontrar la configuración perfecta.', en: 'Spanish Demo', zh: '西班牙语示例' },
    ],
    it: [
        { text: 'Ciao! Benvenuto in Bashi Voice Factory. Questa è una dimostrazione di sintesi vocale di alta qualità. Scegli una voce e regola velocità e tono per trovare le impostazioni perfette per te.', en: 'Italian Demo', zh: '意大利语示例' },
    ]
};

// Initialize Application
document.addEventListener('DOMContentLoaded', init);

async function init() {
    await loadVoices();
    await loadSttModels();
    restoreAutoplayPreference();
    setupEventListeners();
    renderStylePresets();
    renderFirstRunBanner();
    updateCharCount();
    await loadSystemInfo();
    await loadCudaUpgradeStatus();

    // Check for saved language preference
    const savedLang = localStorage.getItem('bashi_lang') || localStorage.getItem('edgetts_lang');
    if (savedLang) {
        switchLanguage(savedLang);
    }
}

function restoreAutoplayPreference() {
    const saved = localStorage.getItem(AUTOPLAY_FIRST_CHUNK_STORAGE_KEY);
    state.autoPlayFirstChunk = saved !== 'false';
    if (elements.autoplayFirstChunk) {
        elements.autoplayFirstChunk.checked = state.autoPlayFirstChunk;
    }
}

// Load Voices from API
async function loadVoices() {
    try {
        const response = await fetch('/api/voices');
        state.voices = await response.json();
        renderVoiceTabs();

    const defaultVoice = state.voices._meta?.default_voice || 'uncle_fu';
        if (!getVoiceCategoryData(state.selectedCategory)) {
            state.selectedCategory = 'all';
        }

        const initialVoices = getVoiceCategoryData(state.selectedCategory)?.voices || [];
        const hasDefault = initialVoices.some(voice => voice.id === defaultVoice);
        state.selectedVoice = hasDefault ? defaultVoice : (initialVoices[0]?.id || defaultVoice);

        renderVoices(state.selectedCategory);
        updateDemoButtons(state.selectedCategory);
    } catch (error) {
        console.error('Failed to load voices:', error);
        showToast('Failed to load voices', 'error');
    }
}

function getVoiceCategories() {
    if (!state.voices) return [];
    return SUPPORTED_LANGUAGE_TABS
        .map(tab => getVoiceCategoryData(tab.id))
        .filter(Boolean);
}

function getVoiceCategoryData(category) {
    if (!state.voices) return null;

    const tab = SUPPORTED_LANGUAGE_TABS.find(item => item.id === category);
    const backendCategory = state.voices[category];
    if (backendCategory && Array.isArray(backendCategory.voices)) {
        return {
            id: category,
            ...backendCategory,
            crossLingual: Boolean(tab?.crossLingual)
        };
    }

    if (tab?.crossLingual && Array.isArray(state.voices.all?.voices)) {
        return {
            id: category,
            category: tab.category_en,
            category_en: tab.category_en,
            category_zh: tab.category_zh,
            voices: state.voices.all.voices,
            crossLingual: true
        };
    }

    return null;
}

function renderVoiceTabs() {
    if (!elements.voiceTabs) return;

    const tabs = getVoiceCategories();
    elements.voiceTabs.innerHTML = tabs.map(category => `
        <button class="voice-tab ${category.id === state.selectedCategory ? 'active' : ''}"
                data-category="${category.id}"
                data-en="${category.category_en || category.category}"
                data-zh="${category.category_zh || category.category}">
            ${state.currentLang === 'zh' ? (category.category_zh || category.category) : (category.category_en || category.category)}
        </button>
    `).join('');
}

// Render Voice Cards
function renderVoices(category) {
    const categoryData = getVoiceCategoryData(category);
    if (!categoryData) return;

    const noteHtml = categoryData.crossLingual ? `
        <div class="voice-grid-note">
            ${state.currentLang === 'zh'
                ? '无母语 speaker - 任何音色都可跨语言合成，但可能带有口音。'
                : 'No native speaker - any voice can synthesize this language, often with an accent.'}
        </div>
    ` : '';

    const cardsHtml = categoryData.voices.map(voice => {
        const badges = Array.isArray(voice.badges) ? voice.badges : [];
        const badgeHtml = badges.map(badge => {
            const label = state.currentLang === 'zh' ? badge.zh : badge.en;
            return `<span class="voice-tag">${escapeHtml(label)}</span>`;
        }).join('');
        const languageLabel = state.currentLang === 'zh' ? voice.language_label_zh : voice.language_label_en;
        const genderLabel = state.currentLang === 'zh'
            ? (voice.gender_zh || voice.gender)
            : (voice.gender_en || voice.gender);
        const styleText = state.currentLang === 'zh'
            ? (voice.style_zh || voice.style)
            : (voice.style_en || voice.style);
        const recommendedClass = voice.recommended_for?.includes(category) ? 'recommended-speaker' : '';
        return `
            <div class="voice-card ${voice.id === state.selectedVoice ? 'selected' : ''} ${recommendedClass}" 
                 data-voice-id="${voice.id}"
                 onclick="selectVoice('${voice.id}')">
                <div class="voice-name">${escapeHtml(voice.name)}</div>
                <div class="voice-meta">
                    <span class="voice-tag">${escapeHtml(genderLabel)}</span>
                    <span class="voice-tag">${escapeHtml(languageLabel)}</span>
                    ${badgeHtml}
                </div>
                <div class="voice-style">${escapeHtml(styleText)}</div>
            </div>
        `;
    }).join('');

    elements.voiceGrid.innerHTML = noteHtml + cardsHtml;
}

// Select Voice
function selectVoice(voiceId) {
    state.selectedVoice = voiceId;

    const preset = getStylePreset();
    if (preset.voiceId && preset.voiceId !== voiceId) {
        state.selectedStylePreset = 'standard_reading';
        renderStylePresets();
    }

    // Update UI
    document.querySelectorAll('.voice-card').forEach(card => {
        card.classList.toggle('selected', card.dataset.voiceId === voiceId);
    });
    scheduleEstimate();
}

// Set Playback Mode
function setPlaybackMode(mode) {
    stopLongPreview();
    state.playbackMode = mode;

    // Update mode buttons
    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });

    // Show/hide sentence-specific settings
    const chunkingSettings = document.getElementById('chunking-settings');
    if (mode === 'sentence') {
        if (elements.settingsSection) elements.settingsSection.style.display = 'block';
        elements.pauseSetting.style.display = 'block';
        elements.modeHint.style.display = 'block';
        if (chunkingSettings) chunkingSettings.style.display = 'block';
        elements.generateBtnText.setAttribute('data-en', 'Generate Chunks');
        elements.generateBtnText.setAttribute('data-zh', '生成跟读片段');
        elements.generateBtnText.textContent = state.currentLang === 'zh' ? '生成跟读片段' : 'Generate Chunks';
        elements.textInput.maxLength = 5000;
    } else {
        if (elements.settingsSection) elements.settingsSection.style.display = 'none';
        elements.pauseSetting.style.display = 'none';
        elements.modeHint.style.display = 'none';
        if (chunkingSettings) chunkingSettings.style.display = 'none';
        elements.generateBtnText.setAttribute('data-en', 'Generate Speech');
        elements.generateBtnText.setAttribute('data-zh', '生成语音');
        elements.generateBtnText.textContent = state.currentLang === 'zh' ? '生成语音' : 'Generate Speech';
        elements.textInput.maxLength = 50000;
    }

    updateCharCount();
    scheduleEstimate();

    // Hide previous results
    elements.playerSection.style.display = 'none';
    elements.sentencePlayerSection.style.display = 'none';
}

// Set Chunking Preset
function setChunkingPreset(preset) {
    // Update button states
    document.querySelectorAll('.chunk-preset-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.preset === preset);
    });

    // Set max words based on preset
    switch (preset) {
        case 'short':
            state.maxWords = 12;
            state.chunkingEnabled = true;
            break;
        case 'medium':
            state.maxWords = 15;
            state.chunkingEnabled = true;
            break;
        case 'long':
            state.maxWords = 20;
            state.chunkingEnabled = true;
            break;
        case 'off':
            state.maxWords = 0;
            state.chunkingEnabled = false;
            break;
    }
    scheduleEstimate();
}

// Set Newline Handling Mode
function setNewlineMode(mode) {
    // mode: 'hard' (each newline is a boundary) or 'flow' (ignore single newlines)
    state.newlineHard = (mode === 'hard');

    document.querySelectorAll('.newline-mode-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });
    scheduleEstimate();
}

// Setup Event Listeners
function setupEventListeners() {
    // Text Input
    elements.textInput.addEventListener('input', updateCharCount);

    if (elements.benchmarkBtn) {
        elements.benchmarkBtn.addEventListener('click', runBenchmark);
    }

    if (elements.firstRunBenchmarkBtn) {
        elements.firstRunBenchmarkBtn.addEventListener('click', () => {
            completeFirstRun();
            runBenchmark();
        });
    }

    if (elements.firstRunDismissBtn) {
        elements.firstRunDismissBtn.addEventListener('click', completeFirstRun);
    }

    if (elements.cudaUpgradeBtn) {
        elements.cudaUpgradeBtn.addEventListener('click', downloadCudaRuntime);
    }

    if (elements.updateCheckBtn) {
        elements.updateCheckBtn.addEventListener('click', () => {
            window.open('https://files.fm/u/juvstxmrez', '_blank', 'noopener');
        });
    }

    // Voice Category Tabs
    if (elements.voiceTabs) {
        elements.voiceTabs.addEventListener('click', (event) => {
            const tab = event.target.closest('.voice-tab');
            if (!tab) return;

            const category = tab.dataset.category;
            state.selectedCategory = category;

            // Update tab UI
            document.querySelectorAll('.voice-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            // Always select the first voice of the new category
            const categoryVoices = getVoiceCategoryData(category)?.voices || [];
            if (categoryVoices.length > 0) {
                state.selectedVoice = categoryVoices[0].id;
            }
            const preset = getStylePreset();
            if (preset.voiceId && preset.voiceId !== state.selectedVoice) {
                state.selectedStylePreset = 'standard_reading';
                renderStylePresets();
            }

            renderVoices(category);
            updateDemoButtons(category);
            scheduleEstimate();
        });
    }

    if (elements.stylePresetGrid) {
        elements.stylePresetGrid.addEventListener('click', (event) => {
            const previewButton = event.target.closest('.style-preview-btn');
            if (previewButton) {
                const presetId = previewButton.dataset.presetPreviewId;
                selectStylePreset(presetId);
                playStylePresetPreview(presetId);
                return;
            }

            const presetButton = event.target.closest('.style-preset-btn');
            if (!presetButton) return;
            selectStylePreset(presetButton.dataset.presetId);
        });
    }

    if (elements.customInstructInput) {
        elements.customInstructInput.addEventListener('input', () => {
            state.customInstruct = elements.customInstructInput.value;
            updateStyleInstructionHint();
            scheduleEstimate();
        });
    }

    // Quick Text Buttons
    document.querySelectorAll('.quick-text-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            elements.textInput.value = btn.dataset.text;
            updateCharCount();
        });
    });

    // Sentence-mode pause slider
    elements.pauseSlider?.addEventListener('input', () => {
        state.pauseDuration = parseFloat(elements.pauseSlider.value);
        elements.pauseValue.textContent = `${state.pauseDuration}s`;
    });

    elements.autoplayFirstChunk?.addEventListener('change', () => {
        state.autoPlayFirstChunk = elements.autoplayFirstChunk.checked;
        localStorage.setItem(
            AUTOPLAY_FIRST_CHUNK_STORAGE_KEY,
            String(state.autoPlayFirstChunk)
        );
    });

    // Generate Button
    elements.generateBtn.addEventListener('click', generateSpeech);
    elements.longStopBtn?.addEventListener('click', stopSynthesis);
    elements.sentenceStopBtn?.addEventListener('click', stopSynthesis);
    elements.longPreviewToggle?.addEventListener('click', toggleLongPreview);

    // Download Button
    if (elements.downloadBtn) {
        elements.downloadBtn.addEventListener('click', downloadAudio);
    }

    // Keyboard shortcut (Ctrl/Cmd + Enter to generate)
    elements.textInput.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            generateSpeech();
        }
    });

    // Sentence audio ended event
    elements.sentenceAudio.addEventListener('ended', onSentenceEnded);
    elements.longPreviewAudio?.addEventListener('ended', onLongPreviewEnded);
    // The complete file takes over the moment the user starts it: otherwise the
    // hidden preview element and #audio-player would play the same content at two
    // different positions.
    elements.audioPlayer?.addEventListener('play', () => {
        if (!state.longPreviewPlaying) return;
        haltLongPreviewAudio();
        setLongPreviewStatus('', '', false);
        updateLongPreviewToggle();
        const progressDiv = document.getElementById('long-text-progress');
        if (progressDiv && state.synthesisComplete) {
            progressDiv.style.display = 'none';
            setLongProgressPlayoutMode(null);
        }
    });

    // TXT File Upload - Click
    if (elements.uploadBtn) {
        elements.uploadBtn.addEventListener('click', () => {
            elements.fileInput.click();
        });
    }

    // TXT File Upload - File selected
    if (elements.fileInput) {
        elements.fileInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) loadTextFile(file);
            e.target.value = ''; // Reset so same file can be re-selected
        });
    }

    // TXT File Upload - Drag & Drop on textarea
    const inputSection = elements.textInput.closest('.input-section');
    if (inputSection) {
        inputSection.addEventListener('dragover', (e) => {
            e.preventDefault();
            if (elements.dropZone) elements.dropZone.classList.add('active');
        });

        inputSection.addEventListener('dragleave', (e) => {
            // Only deactivate if leaving the section entirely
            if (!inputSection.contains(e.relatedTarget)) {
                if (elements.dropZone) elements.dropZone.classList.remove('active');
            }
        });

        inputSection.addEventListener('drop', (e) => {
            e.preventDefault();
            if (elements.dropZone) elements.dropZone.classList.remove('active');
            const file = e.dataTransfer.files[0];
            if (file && file.name.endsWith('.txt')) {
                loadTextFile(file);
            } else {
                const msg = state.currentLang === 'zh' ? '请拖放 .txt 文本文件' : 'Please drop a .txt file';
                showToast(msg, 'error');
            }
        });
    }

    // STT File Upload
    if (elements.sttFileInput) {
        elements.sttFileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                state.sttFile = e.target.files[0];
                showSttFileInfo(state.sttFile);
            }
        });
    }

    if (elements.sttUploadZone) {
        elements.sttUploadZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            elements.sttUploadZone.style.borderColor = 'var(--primary-color)';
        });
        elements.sttUploadZone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            elements.sttUploadZone.style.borderColor = '';
        });
        elements.sttUploadZone.addEventListener('drop', (e) => {
            e.preventDefault();
            elements.sttUploadZone.style.borderColor = '';
            if (e.dataTransfer.files.length > 0) {
                const file = e.dataTransfer.files[0];
                // Check if audio or video
                if (file.type.startsWith('audio/') || file.type.startsWith('video/') || file.name.match(/\.(mp3|mp4|wav|m4a|ogg|flac|aac|wma|msv|mkv)$/i)) {
                    state.sttFile = file;
                    showSttFileInfo(state.sttFile);
                } else {
                    const msg = state.currentLang === 'zh' ? '只支持音频和视频文件' : 'Only audio/video files supported';
                    showToast(msg, 'error');
                }
            }
        });
    }
}

// Update Character Count
function updateCharCount() {
    const count = elements.textInput.value.length;
    const max = elements.textInput.maxLength > 0 ? elements.textInput.maxLength : 50000;
    elements.charCount.textContent = `${count} / ${max}`;

    if (count > max * 0.96) {
        elements.charCount.style.color = '#f5576c';
    } else if (count > max * 0.90) {
        elements.charCount.style.color = '#ffc107';
    } else {
        elements.charCount.style.color = '';
    }
    scheduleEstimate();
}

// Generate Speech
async function generateSpeech() {
    const text = elements.textInput.value.trim();

    if (state.benchmarkInProgress) {
        showToast(t('Speed test is running. Please wait.', '正在测速，请稍候。'), 'info');
        return;
    }

    if (!text) {
        const msg = state.currentLang === 'zh' ? '请输入文本' : 'Please enter some text';
        showToast(msg, 'error');
        return;
    }

    // Only the newest accepted synthesis run may update shared UI/playback state.
    // Older SSE streams can remain alive while a replacement request retries 409.
    const runToken = ++state.runToken;
    stopLongPreview();

    // Get settings
    const instruct = buildInstruct();
    const sentenceMode = state.playbackMode === 'sentence';
    const longMode = !sentenceMode && shouldUseLongSynthesis(text);
    const controller = sentenceMode || longMode ? new AbortController() : null;
    const retryAfterStop = state.retryAfterStop;
    state.retryAfterStop = false;
    if (controller) {
        state.synthesisAbort = controller;
        state.synthesisComplete = false;
        state.synthesisStopped = false;
        setSynthesisStopMode(sentenceMode ? 'sentence' : 'long');
    }

    // Show loading state
    elements.generateBtn.style.display = 'none';
    elements.loading.classList.add('active');
    // Reset loading span text in case a previous sentence-mode run left it
    // pinned to "正在合成第 N/N 句..."
    const loadingSpan = elements.loading.querySelector('span');
    if (loadingSpan) {
        loadingSpan.setAttribute('data-en', 'Generating...');
        loadingSpan.setAttribute('data-zh', '正在生成...');
        loadingSpan.textContent = state.currentLang === 'zh' ? '正在生成...' : 'Generating...';
    }
    elements.playerSection.style.display = 'none';
    elements.sentencePlayerSection.style.display = 'none';
    const progressDiv = document.getElementById('long-text-progress');
    if (progressDiv) {
        progressDiv.style.display = 'none';
        setLongProgressPlayoutMode(null);
    }

    try {
        if (sentenceMode) {
            await generateSentences(text, instruct, controller.signal, retryAfterStop, runToken);
        } else {
            if (longMode) {
                // Hide generic spinner since long audio has its own detailed progress bar
                elements.loading.classList.remove('active');
                await generateLongAudio(text, instruct, controller.signal, retryAfterStop, runToken);
            } else {
                await generateSingleAudio(text, instruct, retryAfterStop, runToken);
            }
        }
    } catch (error) {
        if (runToken !== state.runToken) return;
        if (error.name === 'AbortError') {
            clearLongProgressAnim();
            clearSentenceProgressAnim();
            if (progressDiv && (!longMode || !state.longPreviewPlaying)) {
                progressDiv.style.display = 'none';
                setLongProgressPlayoutMode(null);
            }
            if (sentenceMode) {
                finishSentenceSynthesis(true);
            } else {
                state.synthesisComplete = true;
            }
            showToast(t('Synthesis stopped. Generated chunks are still available.', '已停止合成，已生成的片段仍可使用。'), 'info');
            return;
        }
        if (sentenceMode) {
            finishSentenceSynthesis(false);
        }
        console.error('Synthesis error:', error);
        clearLongProgressAnim();
        clearSentenceProgressAnim();
        if (progressDiv && (!longMode || !state.longPreviewPlaying)) {
            progressDiv.style.display = 'none';
            setLongProgressPlayoutMode(null);
        }
        const msg = state.currentLang === 'zh' ? '生成失败，请重试' : 'Generation failed, please try again';
        showToast(msg, 'error');
    } finally {
        if (runToken === state.runToken) {
            clearLongProgressAnim();
            clearSentenceProgressAnim();
            // Hide loading state
            elements.generateBtn.style.display = 'flex';
            elements.loading.classList.remove('active');
            setSynthesisStopMode(null);
        }
        if (state.synthesisAbort === controller) {
            state.synthesisAbort = null;
        }
        if (longMode && runToken === state.runToken) {
            state.synthesisComplete = true;
        }
    }
}

function setSynthesisStopMode(mode) {
    if (elements.longStopBtn) {
        elements.longStopBtn.style.display = mode === 'long' ? 'inline-flex' : 'none';
    }
    if (elements.sentenceStopBtn) {
        elements.sentenceStopBtn.style.display = mode === 'sentence' ? 'inline-flex' : 'none';
    }
}

function stopSynthesis() {
    if (!state.synthesisAbort) return;
    state.synthesisStopped = true;
    state.synthesisComplete = true;
    state.retryAfterStop = true;
    state.synthesisAbort.abort();
}

function showRestartRetryStatus(groupFinishDeadline = null, retryAfterStop = false, runToken = state.runToken) {
    if (runToken !== state.runToken) return;
    let en = retryAfterStop
        ? 'Stopping previous synthesis...'
        : 'Waiting for the current synthesis to finish...';
    let zh = retryAfterStop
        ? '正在停止上一次合成…'
        : '上一次合成仍在进行，正在等待…';
    if (Number.isFinite(groupFinishDeadline)) {
        const remainingSeconds = Math.ceil((groupFinishDeadline - Date.now()) / 1000);
        if (remainingSeconds > 0) {
            en = `Finishing the previous chunk; starting in up to ${remainingSeconds}s`;
            zh = `上一段合成收尾中，最多约 ${remainingSeconds} 秒后开始`;
        } else {
            en = 'Starting shortly...';
            zh = '即将开始…';
        }
    }
    const statusElements = [
        elements.loading?.querySelector('span'),
        document.getElementById('long-progress-text')
    ];
    statusElements.forEach(element => {
        if (!element) return;
        element.setAttribute('data-en', en);
        element.setAttribute('data-zh', zh);
        element.textContent = state.currentLang === 'zh' ? zh : en;
    });
}

function clearRestartRetryStatus(runToken = state.runToken) {
    if (runToken !== state.runToken) return;
    const initialStatuses = [
        [elements.loading?.querySelector('span'), 'Generating...', '正在生成...'],
        [document.getElementById('long-progress-text'), 'Initializing...', '初始化...']
    ];
    initialStatuses.forEach(([element, en, zh]) => {
        if (!element) return;
        element.setAttribute('data-en', en);
        element.setAttribute('data-zh', zh);
        element.textContent = state.currentLang === 'zh' ? zh : en;
    });
}

function waitForRetryDelay(delayMs, signal) {
    if (signal?.aborted) {
        return Promise.reject(new DOMException('Synthesis aborted', 'AbortError'));
    }
    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
            signal?.removeEventListener('abort', onAbort);
            resolve();
        }, delayMs);
        const onAbort = () => {
            clearTimeout(timer);
            signal?.removeEventListener('abort', onAbort);
            reject(new DOMException('Synthesis aborted', 'AbortError'));
        };
        signal?.addEventListener('abort', onAbort, { once: true });
    });
}

async function postSynthesisWithRetry(
    url,
    payload,
    { signal, retryAfterStop = false, runToken = state.runToken } = {}
) {
    const deadline = Date.now() + RESTART_RETRY_BUDGET_MS;
    let retryIndex = 0;
    let groupFinishDeadline = null;

    while (true) {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal,
            body: JSON.stringify(payload)
        });
        // A newer run may have started while fetch was in flight. Return the
        // response to its caller so any live SSE body is still drained there,
        // but never let an obsolete retry loop keep competing for the engine.
        if (runToken !== state.runToken) return response;
        if (response.status !== 409) {
            if (response.ok) {
                clearRestartRetryStatus(runToken);
            }
            return response;
        }

        const remainingMs = deadline - Date.now();
        if (remainingMs <= 0) {
            return response;
        }

        if (
            retryIndex === 0
            && retryAfterStop
            && url === '/api/synthesize-long'
            && Number.isFinite(state.lastGroupSeconds)
            && state.lastGroupSeconds > 0
        ) {
            groupFinishDeadline = Date.now() + state.lastGroupSeconds * 1000;
        }
        showRestartRetryStatus(groupFinishDeadline, retryAfterStop, runToken);
        const backoffMs = Math.min(
            RESTART_RETRY_BASE_DELAY_MS * (2 ** retryIndex),
            RESTART_RETRY_MAX_DELAY_MS,
            remainingMs
        );
        retryIndex++;
        await waitForRetryDelay(backoffMs, signal);
        if (Date.now() >= deadline) {
            return response;
        }
    }
}

// Generate Single Audio
async function generateSingleAudio(text, instruct, retryAfterStop = false, runToken = state.runToken) {
    const response = await postSynthesisWithRetry(
        '/api/synthesize',
        {
            text: text,
            voice: state.selectedVoice,
            instruct: instruct
        },
        { retryAfterStop, runToken }
    );

    const result = await response.json();
    if (runToken !== state.runToken) return;

    if (result.success) {
        state.currentAudioUrl = result.audio_url;
        elements.audioPlayer.src = result.audio_url;
        elements.playerSection.style.display = 'block';

        // Auto-play
        elements.audioPlayer.play().catch(() => { });

        const msg = state.currentLang === 'zh' ? '语音生成成功！' : 'Speech generated successfully!';
        showToast(msg, 'success');
    } else {
        const errorMsg = state.currentLang === 'zh' ? result.error_zh : result.error;
        showToast(errorMsg, 'error');
    }
}

function setLongPreviewStatus(en, zh, visible = true) {
    if (!elements.longPreviewStatus) return;
    elements.longPreviewStatus.setAttribute('data-en', en);
    elements.longPreviewStatus.setAttribute('data-zh', zh);
    elements.longPreviewStatus.textContent = state.currentLang === 'zh' ? zh : en;
    elements.longPreviewStatus.style.display = visible ? 'inline' : 'none';
}

function setLongProgressPlayoutMode(mode) {
    const progressDiv = document.getElementById('long-text-progress');
    if (!progressDiv) return;

    const spinner = progressDiv.querySelector('.spinner');
    const headline = document.getElementById('long-progress-headline');
    const metrics = document.getElementById('long-progress-metrics');
    const hint = document.getElementById('long-progress-hint');
    const isPlayout = mode === 'stopped' || mode === 'completed';
    let en = 'Generating...';
    let zh = '正在生成...';
    if (mode === 'stopped') {
        en = 'Synthesis stopped';
        zh = '已停止合成';
    } else if (mode === 'completed') {
        en = 'Synthesis complete';
        zh = '合成完成';
    }

    if (spinner) spinner.style.display = isPlayout ? 'none' : '';
    if (headline) {
        headline.setAttribute('data-en', en);
        headline.setAttribute('data-zh', zh);
        headline.textContent = state.currentLang === 'zh' ? zh : en;
    }
    if (metrics) metrics.style.display = isPlayout ? 'none' : '';
    if (hint) hint.style.display = isPlayout ? 'none' : '';
}

function updateLongPreviewToggle() {
    if (!elements.longPreviewToggle) return;
    const icon = elements.longPreviewToggle.querySelector('.long-preview-toggle-icon');
    const label = elements.longPreviewToggle.querySelector('.long-preview-toggle-text');
    const audible = state.longPreviewPlaying && !state.longPreviewMuted;
    elements.longPreviewToggle.disabled = state.longChunks.length === 0 || state.longPreviewGiveUp;
    if (icon) icon.textContent = audible ? '🔇' : '🔊';
    if (label) {
        const en = audible ? 'Mute preview' : 'Preview';
        const zh = audible ? '静音试听' : '试听';
        label.setAttribute('data-en', en);
        label.setAttribute('data-zh', zh);
        label.textContent = state.currentLang === 'zh' ? zh : en;
    }
}

function resetLongPreviewState() {
    state.longChunks = [];
    state.longChunkIndex = 0;
    state.longPreviewPlaying = false;
    state.longPreviewWaiting = false;
    state.longPreviewMuted = false;
    state.longChunkArrivalTimes = [];
    state.longPreviewStrategyDecided = false;
    state.longPreviewBufferTarget = 0;
    state.longPreviewGiveUp = false;
    state.longTotal = 0;
    state.longFinalAudioReady = false;
    // Cross-run group timing telemetry is deliberately preserved: restart status
    // still needs the previous run after stopLongPreview clears per-run state.
}

function haltLongPreviewAudio() {
    if (elements.longPreviewAudio) {
        elements.longPreviewAudio.pause();
        elements.longPreviewAudio.removeAttribute('src');
        elements.longPreviewAudio.muted = false;
        elements.longPreviewAudio.load();
    }
    state.longPreviewPlaying = false;
    state.longPreviewWaiting = false;
    state.longPreviewMuted = false;
}

function stopLongPreview() {
    haltLongPreviewAudio();
    resetLongPreviewState();
    setLongPreviewStatus('', '', false);
    updateLongPreviewToggle();
}

function completeLongPreviewPlayback() {
    if (!state.longPreviewPlaying && !state.longPreviewWaiting) return;
    haltLongPreviewAudio();
    setLongPreviewStatus('', '', false);
    updateLongPreviewToggle();
    const progressDiv = document.getElementById('long-text-progress');
    if (progressDiv) {
        progressDiv.style.display = 'none';
        setLongProgressPlayoutMode(null);
    }
    if (state.longFinalAudioReady) {
        showToast(
            t(
                'Complete audio is ready for seeking and download.',
                '完整音频已就绪，可拖动和下载。'
            ),
            'success'
        );
    } else if (state.synthesisStopped) {
        showToast(t('Generated preview playback complete.', '已生成的试听片段播放完毕。'), 'info');
    }
}

function updateLongPreviewBufferingStatus() {
    const buffered = state.longChunks.length;
    const total = state.longTotal || buffered;
    setLongPreviewStatus(
        `Buffering for continuous playback... (${buffered}/${total} chunks buffered)`,
        `正在缓冲，稍后连续播放…（已缓冲 ${buffered}/${total} 组）`
    );
}

function resolveLongPreviewWaiting() {
    if (!state.longPreviewWaiting) return;
    if (state.longPreviewGiveUp) {
        setLongPreviewStatus(
            'This machine synthesizes slower than real time; playback will start when synthesis finishes.',
            '本机生成较慢，将在合成完成后连续播放。'
        );
        return;
    }

    if (!state.longPreviewStrategyDecided) {
        if (state.longChunkArrivalTimes.length < 2) {
            setLongPreviewStatus('Waiting for next chunk...', '等待下一组合成…');
            return;
        }
        const intervals = state.longChunkArrivalTimes.slice(1).map(
            (arrival, index) => arrival - state.longChunkArrivalTimes[index]
        );
        const tSeconds = intervals.reduce((sum, value) => sum + value, 0) / intervals.length;
        const durations = state.longChunks
            .map(chunk => Number(chunk.duration))
            .filter(duration => duration > 0);
        const dSeconds = durations.reduce((sum, value) => sum + value, 0) / durations.length;
        const strategy = calculateLongPreviewBufferStrategy({
            n: state.longTotal || state.longChunks.length,
            t: tSeconds,
            d: dSeconds,
            elapsed: state.longChunks.length * tSeconds
        });
        state.longPreviewStrategyDecided = true;
        state.longPreviewBufferTarget = strategy.chunksNeeded;
        state.longPreviewGiveUp = strategy.giveUp;
        if (strategy.giveUp) {
            state.longPreviewPlaying = false;
            updateLongPreviewToggle();
            setLongPreviewStatus(
                'This machine synthesizes slower than real time; playback will start when synthesis finishes.',
                '本机生成较慢，将在合成完成后连续播放。'
            );
            return;
        }
    }

    if (
        state.longChunkIndex < state.longChunks.length
        && state.longChunks.length >= state.longPreviewBufferTarget
    ) {
        state.longPreviewWaiting = false;
        setLongPreviewStatus('', '', false);
        playLongPreview(state.longChunkIndex);
        return;
    }
    updateLongPreviewBufferingStatus();
}

function playLongPreview(index) {
    if (state.longPreviewGiveUp) return;
    if (index >= state.longChunks.length) {
        if (!state.synthesisComplete) {
            state.longChunkIndex = index;
            state.longPreviewWaiting = true;
            // Keep the preview session active across a planned buffer wait so a
            // later `done` event never jumps the listener back to final-audio 0:00.
            state.longPreviewPlaying = true;
            resolveLongPreviewWaiting();
            updateLongPreviewToggle();
            return;
        }
        completeLongPreviewPlayback();
        return;
    }

    elements.audioPlayer.pause();
    state.longChunkIndex = index;
    state.longPreviewWaiting = false;
    state.longPreviewPlaying = true;
    setLongPreviewStatus('', '', false);

    // Keep native <audio> + MP3 for Windows/macOS/Linux browser parity; do not
    // replace this preview path with MSE or custom WebAudio decoding.
    elements.longPreviewAudio.src = state.longChunks[index].audio_url;
    elements.longPreviewAudio.muted = state.longPreviewMuted;
    elements.longPreviewAudio.play().catch(() => {
        state.longPreviewPlaying = false;
        updateLongPreviewToggle();
    });
    updateLongPreviewToggle();
}

function onLongPreviewEnded() {
    if (!state.longPreviewPlaying) return;
    state.longChunkIndex++;
    setTimeout(() => {
        if (state.longPreviewPlaying) {
            playLongPreview(state.longChunkIndex);
        }
    }, LONG_PREVIEW_GAP_MS);
}

function toggleLongPreview() {
    if (state.longChunks.length === 0 || state.longPreviewGiveUp) return;
    if (!state.longPreviewPlaying) {
        state.longPreviewMuted = false;
        playLongPreview(Math.min(state.longChunkIndex, state.longChunks.length - 1));
        return;
    }
    state.longPreviewMuted = !state.longPreviewMuted;
    elements.longPreviewAudio.muted = state.longPreviewMuted;
    updateLongPreviewToggle();
}

function handleLongPreviewChunk(data, runToken) {
    if (runToken !== state.runToken) return;
    if (!data.audio_url) return;
    state.longTotal = Number(data.total) || state.longTotal;
    state.longChunks.push({
        audio_url: data.audio_url,
        filename: data.filename,
        duration: Number(data.duration) || 0,
        chunk: data.chunk
    });
    state.longChunkArrivalTimes.push(performance.now() / 1000);
    if (state.longChunkArrivalTimes.length >= 2) {
        const intervals = state.longChunkArrivalTimes.slice(1).map(
            (arrival, index) => arrival - state.longChunkArrivalTimes[index]
        );
        state.lastGroupSeconds = intervals.reduce((sum, value) => sum + value, 0)
            / intervals.length;
    }
    updateLongPreviewToggle();

    if (
        state.longChunks.length === 1
        && state.autoPlayFirstChunk
        && state.longTotal > 1
    ) {
        playLongPreview(0);
    } else if (state.longPreviewWaiting) {
        resolveLongPreviewWaiting();
    }
}

// Generate Long Audio via SSE
async function generateLongAudio(text, instruct, signal, retryAfterStop = false, runToken = state.runToken) {
    const progressDiv = document.getElementById('long-text-progress');
    const fill = document.getElementById('long-progress-fill');
    const textEl = document.getElementById('long-progress-text');
    const countEl = document.getElementById('long-progress-count');

    stopLongPreview();
    setLongProgressPlayoutMode(null);
    state.synthesisComplete = false;
    progressDiv.style.display = 'block';
    fill.style.width = '0%';
    setProgressAnim(fill, true);
    const estimatedGroupCount = state.eta?.group_count;
    const initialGroupTotal = Number.isInteger(estimatedGroupCount) && estimatedGroupCount >= 0
        ? estimatedGroupCount
        : 0;
    countEl.textContent = `0 / ${initialGroupTotal}`;

    // Switch to English text immediately if needed to avoid flicker
    textEl.setAttribute('data-en', 'Initializing...');
    textEl.setAttribute('data-zh', '初始化...');
    textEl.textContent = state.currentLang === 'zh' ? '初始化...' : 'Initializing...';

    try {
        const response = await postSynthesisWithRetry(
            '/api/synthesize-long',
            {
                text: text,
                voice: state.selectedVoice,
                instruct: instruct
            },
            { signal, retryAfterStop, runToken }
        );

        if (!response.ok) {
            if (runToken !== state.runToken) return;
            clearLongProgressAnim();
            progressDiv.style.display = 'none';
            setLongProgressPlayoutMode(null);
            let errBody = {};
            try { errBody = await response.json(); } catch (_) { /* non-JSON body */ }
            const errorMsg = state.currentLang === 'zh'
                ? (errBody.error_zh || errBody.error || '长文本生成失败')
                : (errBody.error || errBody.error_zh || 'Long text generation failed');
            showToast(errorMsg, 'error');
            return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const dataStr = line.substring(6).trim();
                    if (!dataStr) continue;

                    const data = JSON.parse(dataStr);

                    if (data.status === 'generating') {
                        if (runToken !== state.runToken) continue;
                        state.longTotal = Number(data.total) || state.longTotal;
                        const percent = ((data.chunk - 1) / data.total) * 100;
                        fill.style.width = `${percent}%`;
                        countEl.textContent = `${data.chunk} / ${data.total}`;

                        textEl.setAttribute('data-en', `Generating group ${data.chunk}...`);
                        textEl.setAttribute('data-zh', `正在生成第 ${data.chunk} 组...`);
                        textEl.textContent = state.currentLang === 'zh' ? `正在生成第 ${data.chunk} 组...` : `Generating group ${data.chunk}...`;
                    }
                    else if (data.status === 'chunk_done') {
                        handleLongPreviewChunk(data, runToken);
                    }
                    else if (data.status === 'merging') {
                        if (runToken !== state.runToken) continue;
                        clearLongProgressAnim();
                        fill.style.width = '95%';
                        textEl.setAttribute('data-en', 'Merging audio files...');
                        textEl.setAttribute('data-zh', '正在合并音频文件...');
                        textEl.textContent = state.currentLang === 'zh' ? '正在合并音频文件...' : 'Merging audio files...';
                    }
                    else if (data.status === 'done') {
                        if (runToken !== state.runToken) continue;
                        clearLongProgressAnim();
                        fill.style.width = '100%';
                        state.currentAudioUrl = data.audio_url_mp3;
                        elements.audioPlayer.src = data.audio_url_mp3;
                        state.longFinalAudioReady = true;
                        state.synthesisComplete = true;
                        elements.playerSection.style.display = 'block';

                        // `chunk_done` is optional: a skipped group or preview
                        // encoding failure can leave the preview waiting for an
                        // index that will never arrive. Once `done` is known, play
                        // any remaining preview URL or fall back to the final file.
                        if (
                            state.longPreviewWaiting
                            && !state.longPreviewGiveUp
                            && state.longChunkIndex < state.longChunks.length
                        ) {
                            state.longPreviewWaiting = false;
                            playLongPreview(state.longChunkIndex);
                        } else if (
                            state.longPreviewWaiting
                            && state.longChunkIndex >= state.longChunks.length
                        ) {
                            haltLongPreviewAudio();
                            setLongPreviewStatus('', '', false);
                        }

                        const previewContinues = state.longPreviewPlaying && !state.longPreviewMuted;
                        if (previewContinues) {
                            setLongProgressPlayoutMode('completed');
                            progressDiv.style.display = 'block';
                            setLongPreviewStatus(
                                'Complete audio is ready; finishing streamed preview...',
                                '完整音频已就绪，正在播完流式试听…'
                            );
                        } else {
                            haltLongPreviewAudio();
                            updateLongPreviewToggle();
                            progressDiv.style.display = 'none';
                            setLongProgressPlayoutMode(null);
                            elements.audioPlayer.play().catch(() => { });
                            const msg = state.currentLang === 'zh'
                                ? '长文本语音生成完成！'
                                : 'Long text speech generated successfully!';
                            showToast(msg, 'success');
                        }

                        // Hide loading spinner since we are done
                        elements.generateBtn.style.display = 'flex';
                        elements.loading.classList.remove('active');
                        return;
                    }
                    else if (data.status === 'error') {
                        if (runToken !== state.runToken) continue;
                        clearLongProgressAnim();
                        throw new Error(data.error);
                    }
                }
            }
        }
    } catch (error) {
        if (runToken !== state.runToken) return;
        if (error.name === 'AbortError') {
            if (state.longPreviewPlaying) {
                setLongProgressPlayoutMode('stopped');
                progressDiv.style.display = 'block';
                setLongPreviewStatus(
                    'Synthesis stopped; playing generated preview chunks...',
                    '合成已停止，正在播完已生成的试听片段…'
                );
            } else {
                progressDiv.style.display = 'none';
                setLongProgressPlayoutMode(null);
            }
            throw error;
        }
        console.error('Long synthesis error:', error);
        clearLongProgressAnim();
        if (!state.longPreviewPlaying) {
            progressDiv.style.display = 'none';
            setLongProgressPlayoutMode(null);
        }
        const msg = state.currentLang === 'zh' ? '长文本生成失败，请重试' : 'Long text generation failed, please try again';
        showToast(msg, 'error');
        throw error; // Let main logic catch it
    } finally {
        if (runToken === state.runToken) {
            clearLongProgressAnim();
        }
    }
}

// Generate Sentences/Chunks (SSE over POST)
// Route streams one `generating` event then one `sentence_done` event per chunk,
// followed by `done` (or `error`). We consume with fetch+ReadableStream because
// EventSource is GET-only and can't send a JSON body.
async function generateSentences(text, instruct, signal, retryAfterStop = false, runToken = state.runToken) {
    setProgressAnim(elements.progressFill, true);

    // Fresh run: reset state before opening the stream so Stop is available
    // while the first chunk is still being generated.
    state.sentences = [];
    state.sentenceTotal = 0;
    state.currentSentenceIndex = 0;
    state.isPlaying = false;
    state.isPaused = false;
    state.waitingForNextChunk = false;
    state.synthesisComplete = false;
    state.synthesisStopped = false;
    updateSentencePlaybackStatus();
    elements.sentencePlayerSection.style.display = 'block';
    renderSentenceList();
    updateProgress();
    updatePauseButton();

    const response = await postSynthesisWithRetry(
        '/api/synthesize-sentences',
        {
            text: text,
            voice: state.selectedVoice,
            instruct: instruct,
            max_words: state.maxWords,
            newline_hard: state.newlineHard
        },
        { signal, retryAfterStop, runToken }
    );

    if (!response.ok) {
        if (runToken !== state.runToken) return;
        clearSentenceProgressAnim();
        state.synthesisComplete = true;
        let errBody = {};
        try { errBody = await response.json(); } catch (_) { /* non-JSON body */ }
        const errorMsg = state.currentLang === 'zh'
            ? (errBody.error_zh || errBody.error || '生成失败')
            : (errBody.error || errBody.error_zh || 'Generation failed');
        showToast(errorMsg, 'error');
        return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let streamDone = false;

    try {
        while (!streamDone) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            let sepIdx;
            while ((sepIdx = buffer.indexOf('\n\n')) >= 0) {
                const frame = buffer.slice(0, sepIdx);
                buffer = buffer.slice(sepIdx + 2);
                if (!frame.startsWith('data: ')) continue;
                let event;
                try {
                    event = JSON.parse(frame.slice(6));
                } catch (_) {
                    continue;  // skip malformed frame
                }
                if (handleSentenceEvent(event, runToken)) {
                    streamDone = true;
                    break;
                }
            }
        }
    } finally {
        if (runToken === state.runToken) {
            clearSentenceProgressAnim();
        }
    }
    if (runToken === state.runToken && !state.synthesisComplete) {
        finishSentenceSynthesis(false);
    }
}

function finishSentenceSynthesis(stopped = false) {
    state.synthesisComplete = true;
    state.synthesisStopped = stopped || state.synthesisStopped;
    if (state.waitingForNextChunk && state.currentSentenceIndex >= state.sentences.length) {
        completeSentencePlayback();
    }
}

// Handle one SSE frame from /api/synthesize-sentences. Returns true to stop reading.
// On `error` we keep already-generated sentences playable and just halt the stream.
function handleSentenceEvent(event, runToken = state.runToken) {
    if (runToken !== state.runToken) return false;
    if (typeof event.total === 'number' && event.total > 0) {
        state.sentenceTotal = event.total;
    }

    if (event.status === 'generating') {
        const loadingSpan = elements.loading.querySelector('span');
        if (loadingSpan) {
            const position = (event.index ?? 0) + 1;
            const total = event.total ?? state.sentenceTotal;
            const en = `Generating chunk ${position}/${total}...`;
            const zh = `正在合成第 ${position}/${total} 句...`;
            loadingSpan.setAttribute('data-en', en);
            loadingSpan.setAttribute('data-zh', zh);
            loadingSpan.textContent = state.currentLang === 'zh' ? zh : en;
        }
        return false;
    }

    if (event.status === 'sentence_done') {
        state.sentences.push({
            text: event.text,
            audio_url: event.audio_url,
            filename: event.filename
        });
        renderSentenceList();
        updateProgress();
        if (state.waitingForNextChunk && state.currentSentenceIndex === state.sentences.length - 1) {
            if (state.isPlaying) {
                playSentence(state.currentSentenceIndex);
            }
        } else if (state.sentences.length === 1 && state.autoPlayFirstChunk) {
            playAllSentences();
        }
        return false;
    }

    if (event.status === 'done') {
        clearSentenceProgressAnim();
        finishSentenceSynthesis(false);
        const total = event.total ?? state.sentenceTotal;
        const chunkWord = state.currentLang === 'zh' ? '个片段' : ' chunks';
        const msg = state.currentLang === 'zh'
            ? `已生成 ${total}${chunkWord}！`
            : `Generated ${total}${chunkWord}!`;
        showToast(msg, 'success');
        return true;
    }

    if (event.status === 'error') {
        clearSentenceProgressAnim();
        finishSentenceSynthesis(false);
        const errorMsg = event.error || (state.currentLang === 'zh' ? '生成失败' : 'Generation failed');
        showToast(errorMsg, 'error');
        return true;
    }

    return false;
}

// Render Sentence List
function renderSentenceList() {
    elements.sentenceList.innerHTML = state.sentences.map((s, i) => `
        <div class="sentence-item" id="sentence-${i}" onclick="playSentence(${i})">
            <span class="sentence-number">${i + 1}</span>
            <span class="sentence-text">${escapeHtml(s.text)}</span>
            <button class="sentence-play-btn" onclick="event.stopPropagation(); playSentence(${i})" title="Play">▶️</button>
            <button class="sentence-play-btn" onclick="downloadSentence(${i}, event)" title="Download">⬇️</button>
        </div>
    `).join('');
}

function downloadSentence(index, event) {
    event?.stopPropagation();
    const sentence = state.sentences[index];
    if (!sentence) return;
    const link = document.createElement('a');
    link.href = sentence.audio_url;
    link.download = sentence.filename || `bashi-chunk-${index + 1}.mp3`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// Escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Update Progress
// Uses state.sentenceTotal (authoritative from SSE `total` field) so the bar
// doesn't drift as chunks stream in. Falls back to actual length when total
// hasn't arrived yet (e.g. first paint before any event).
function updateProgress() {
    const total = state.sentenceTotal || state.sentences.length;
    const current = state.currentSentenceIndex;
    const progress = total > 0 ? (current / total) * 100 : 0;

    elements.progressFill.style.width = `${progress}%`;
    elements.sentenceProgress.textContent = `${current} / ${total}`;
}

// Play Single Sentence
function playSentence(index) {
    if (index >= state.sentences.length) {
        if (!state.synthesisComplete) {
            state.waitingForNextChunk = true;
            updateSentencePlaybackStatus();
            return;
        }
        completeSentencePlayback();
        return;
    }

    state.waitingForNextChunk = false;
    updateSentencePlaybackStatus();

    // Update UI - remove previous states
    document.querySelectorAll('.sentence-item').forEach((el, i) => {
        el.classList.remove('playing');
        if (i < index) {
            el.classList.add('completed');
        } else {
            el.classList.remove('completed');
        }
    });

    // Highlight current sentence
    const currentEl = document.getElementById(`sentence-${index}`);
    if (currentEl) {
        currentEl.classList.add('playing');
        currentEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    // Keep native <audio> + MP3 for Windows/macOS/Linux browser parity; do not
    // replace this path with MSE or custom WebAudio decoding.
    elements.sentenceAudio.src = state.sentences[index].audio_url;
    elements.sentenceAudio.play().catch(() => { });

    state.currentSentenceIndex = index;
    updateProgress();
}

// Play All Sentences
function playAllSentences() {
    if (state.sentences.length === 0) return;

    if (state.currentSentenceIndex >= state.sentences.length) {
        state.currentSentenceIndex = 0;
    }
    state.isPlaying = true;
    state.isPaused = false;
    updatePauseButton();
    playSentence(state.currentSentenceIndex);
}

// Toggle Pause/Continue Playback
function pausePlayback() {
    if (state.isPaused) {
        // Continue playback
        state.isPaused = false;
        state.isPlaying = true;
        updatePauseButton();
        if (state.waitingForNextChunk && state.currentSentenceIndex < state.sentences.length) {
            playSentence(state.currentSentenceIndex);
        } else {
            elements.sentenceAudio.play().catch(() => { });
        }
    } else {
        // Pause playback
        state.isPaused = true;
        state.isPlaying = false;
        updatePauseButton();
        elements.sentenceAudio.pause();
    }
}

// Update Pause Button State
function updatePauseButton() {
    const pauseBtn = document.getElementById('pause-btn');
    if (!pauseBtn) return;

    const iconSpan = pauseBtn.querySelector('span:first-child');
    const textSpan = pauseBtn.querySelector('span:last-child');

    if (state.isPaused) {
        iconSpan.textContent = '▶️';
        textSpan.setAttribute('data-en', 'Continue');
        textSpan.setAttribute('data-zh', '继续');
        textSpan.textContent = state.currentLang === 'zh' ? '继续' : 'Continue';
    } else {
        iconSpan.textContent = '⏸️';
        textSpan.setAttribute('data-en', 'Pause');
        textSpan.setAttribute('data-zh', '暂停');
        textSpan.textContent = state.currentLang === 'zh' ? '暂停' : 'Pause';
    }
}

// Reset Playback
function resetPlayback() {
    state.isPlaying = false;
    state.isPaused = false;
    state.currentSentenceIndex = 0;
    state.waitingForNextChunk = false;
    elements.sentenceAudio.pause();
    updateSentencePlaybackStatus();

    // Reset UI
    document.querySelectorAll('.sentence-item').forEach(el => {
        el.classList.remove('playing', 'completed');
    });

    updateProgress();
    updatePauseButton();
}

// On Sentence Ended
function onSentenceEnded() {
    if (!state.isPlaying) return;

    // Mark current as completed
    const currentEl = document.getElementById(`sentence-${state.currentSentenceIndex}`);
    if (currentEl) {
        currentEl.classList.remove('playing');
        currentEl.classList.add('completed');
    }

    state.currentSentenceIndex++;
    updateProgress();

    // Wait for the configured pause, then either play the ready chunk or enter
    // the waiting state until sentence_done supplies the awaited index.
    setTimeout(() => {
        if (state.isPlaying) {
            playSentence(state.currentSentenceIndex);
        }
    }, state.pauseDuration * 1000);
}

function updateSentencePlaybackStatus() {
    if (!elements.sentencePlaybackStatus) return;
    elements.sentencePlaybackStatus.style.display = state.waitingForNextChunk ? 'inline' : 'none';
}

function completeSentencePlayback() {
    if (!state.isPlaying && !state.waitingForNextChunk) return;
    state.isPlaying = false;
    state.waitingForNextChunk = false;
    updateSentencePlaybackStatus();
    const msg = state.currentLang === 'zh' ? '播放完成！' : 'Playback complete!';
    showToast(msg, 'success');
}

// Update Demo Buttons based on selected language
function updateDemoButtons(category) {
    const demos = DEMO_TEXTS[category] || DEMO_TEXTS['en'];
    const container = document.querySelector('.quick-texts');
    if (!container) return;

    // Remove existing quick-text-btn elements (keep upload button and file input)
    container.querySelectorAll('.quick-text-btn').forEach(btn => btn.remove());

    // Insert new demo buttons before the upload button
    const uploadBtn = container.querySelector('.upload-btn');
    demos.forEach(demo => {
        const btn = document.createElement('button');
        btn.className = 'quick-text-btn';
        btn.dataset.text = demo.text;
        btn.dataset.en = demo.en;
        btn.dataset.zh = demo.zh;
        btn.textContent = state.currentLang === 'zh' ? demo.zh : demo.en;
        btn.addEventListener('click', () => {
            elements.textInput.value = demo.text;
            updateCharCount();
        });
        container.insertBefore(btn, uploadBtn);
    });
}

// Load Text File (with comprehensive encoding auto-detection)
function loadTextFile(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
        const buffer = e.target.result;

        // Step 1: Try UTF-8 first
        let text = new TextDecoder('utf-8').decode(buffer);
        if (!text.includes('\uFFFD')) {
            finishLoadText(text, file);
            return;
        }

        // Step 2: Try multi-byte encodings (fatal mode throws on invalid sequences)
        const multiByteEncodings = ['gbk', 'shift-jis', 'euc-kr'];
        for (const enc of multiByteEncodings) {
            try {
                text = new TextDecoder(enc, { fatal: true }).decode(buffer);
                finishLoadText(text, file);
                return;
            } catch { /* not this encoding, continue */ }
        }

        // Step 3: Try single-byte encodings with Unicode range heuristics
        const singleByteEncodings = [
            { enc: 'windows-1251', test: /[\u0400-\u04FF]/ },   // Cyrillic (Russian)
            { enc: 'windows-1253', test: /[\u0370-\u03FF]/ },   // Greek
            { enc: 'windows-1256', test: /[\u0600-\u06FF]/ },   // Arabic
            { enc: 'windows-1252', test: /[\u00C0-\u00FF]/ },   // Latin extended (French/German/Spanish/Portuguese)
        ];
        for (const { enc, test } of singleByteEncodings) {
            try {
                const decoded = new TextDecoder(enc).decode(buffer);
                if (test.test(decoded)) {
                    finishLoadText(decoded, file);
                    return;
                }
            } catch { /* continue */ }
        }

        // Step 4: Final fallback — ISO-8859-1 (never fails)
        text = new TextDecoder('iso-8859-1').decode(buffer);
        finishLoadText(text, file);
    };
    reader.readAsArrayBuffer(file);
}

function finishLoadText(text, file) {
    // Truncate to the current textarea maxlength (5000 in shadowing mode, 50000 in single mode)
    const maxLen = elements.textInput.maxLength > 0 ? elements.textInput.maxLength : 50000;
    if (text.length > maxLen) {
        text = text.substring(0, maxLen);
        const msg = state.currentLang === 'zh'
            ? `文件已截断至${maxLen.toLocaleString()}字符上限`
            : `File truncated to ${maxLen.toLocaleString()} character limit`;
        showToast(msg, 'info');
    }
    elements.textInput.value = text;
    updateCharCount();
    const msg = state.currentLang === 'zh'
        ? `已加载文件: ${file.name}`
        : `Loaded file: ${file.name}`;
    showToast(msg, 'info');
}

// Download Audio (with format conversion)
async function downloadAudio() {
    if (!state.currentAudioUrl) return;

    const format = elements.formatSelect ? elements.formatSelect.value : 'mp3';
    const mp3Filename = state.currentAudioUrl.split('/').pop();

    if (format === 'mp3') {
        // Direct MP3 download, no conversion needed
        const link = document.createElement('a');
        link.href = state.currentAudioUrl;
        link.download = `edge-tts-${Date.now()}.mp3`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    } else {
        // Convert via backend
        const msg = state.currentLang === 'zh' ? `正在转换为 ${format.toUpperCase()}...` : `Converting to ${format.toUpperCase()}...`;
        showToast(msg, 'info');

        try {
            const response = await fetch('/api/convert', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filename: mp3Filename, format: format })
            });
            const data = await response.json();
            if (data.success) {
                const link = document.createElement('a');
                link.href = `/api/download/${data.filename}`;
                link.download = `edge-tts-${Date.now()}.${format}`;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
            } else {
                const errMsg = state.currentLang === 'zh' ? '转换失败' : 'Conversion failed';
                showToast(errMsg, 'error');
            }
        } catch (err) {
            console.error('Format conversion error:', err);
            const errMsg = state.currentLang === 'zh' ? '转换失败' : 'Conversion failed';
            showToast(errMsg, 'error');
        }
    }
}

// Language Switching
function switchLanguage(lang) {
    state.currentLang = lang;
    localStorage.setItem('bashi_lang', lang);

    // Update language buttons
    document.querySelectorAll('.lang-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.lang === lang);
    });

    // Update HTML lang attribute
    document.documentElement.setAttribute('data-lang', lang);

    // Update all translatable elements
    document.querySelectorAll('[data-en][data-zh]').forEach(el => {
        el.textContent = el.getAttribute(`data-${lang}`);
    });

    // Update textarea placeholder
    const textarea = elements.textInput;
    if (textarea.dataset.placeholderEn && textarea.dataset.placeholderZh) {
        textarea.placeholder = textarea.getAttribute(`data-placeholder-${lang}`);
    }

    renderVoiceTabs();
    renderVoices(state.selectedCategory);
    renderStylePresets();
    renderSystemInfo();
    renderCudaUpgrade();
    renderBenchmarkReferencePanel(state.eta?.references);
    renderEta();
    renderSpeakerIdControls();
}

// Toast Notification
function showToast(message, type = 'info') {
    const toast = elements.toast;
    toast.querySelector('.toast-message').textContent = message;
    toast.className = `toast ${type} show`;

    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

// Toggle Donation Section
function toggleDonation() {
    const content = document.getElementById('donation-content');
    const toggle = document.getElementById('donation-toggle');

    if (content.classList.contains('show')) {
        content.classList.remove('show');
        toggle.classList.remove('open');
    } else {
        content.classList.add('show');
        toggle.classList.add('open');
        checkQRImages();
    }
}

// Check if QR images exist and show hint if missing
function checkQRImages() {
    const qrCodes = document.getElementById('qr-codes');
    const hint = document.getElementById('qr-missing-hint');

    // Check after a short delay to allow onerror handlers to fire
    setTimeout(() => {
        const visibleQRs = qrCodes.querySelectorAll('.qr-item:not([style*="display: none"])');
        if (visibleQRs.length === 0 && hint) {
            hint.style.display = 'block';
        }
    }, 100);
}

// Expose functions to global scope
window.switchLanguage = switchLanguage;
window.selectVoice = selectVoice;
window.setPlaybackMode = setPlaybackMode;
window.setChunkingPreset = setChunkingPreset;
window.setNewlineMode = setNewlineMode;
window.playSentence = playSentence;
window.playAllSentences = playAllSentences;
window.pausePlayback = pausePlayback;
window.resetPlayback = resetPlayback;
window.toggleDonation = toggleDonation;

// STT functions
window.switchAppTab = switchAppTab;
window.onSttModelChange = onSttModelChange;
window.onSttLangChange = onSttLangChange;
window.downloadSelectedModel = downloadSelectedModel;
window.downloadSpeakerModel = downloadSpeakerModel;
window.onSpeakerIdToggleChange = onSpeakerIdToggleChange;
window.clearSttFile = clearSttFile;
window.startTranscription = startTranscription;
window.exportTranscription = exportTranscription;
window.copySttResult = copySttResult;

/* ===============================================
   v3.1 - STT Logic
   =============================================== */

// Switch Main App Tab
function switchAppTab(tabId) {
    state.currentAppTab = tabId;
    document.querySelectorAll('.app-tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`.app-tab[data-tab="${tabId}"]`).classList.add('active');

    document.querySelectorAll('.app-view').forEach(v => v.classList.remove('active'));
    document.getElementById(tabId === 'tts' ? 'tts-container' : 'stt-container').classList.add('active');
}

// Load STT Models
async function loadSttModels() {
    try {
        const response = await fetch('/api/stt/models');
        const data = await response.json();
        
        elements.sttModelSelect.innerHTML = '';
        const allModels = [...data.installed, ...data.available];
        state.sttModels = allModels;
        state.speakerDiarization = data.speaker_diarization || null;
        
        allModels.forEach(m => {
            const isInstalled = data.installed.some(inst => inst.id === m.id);
            const opt = document.createElement('option');
            opt.value = m.id;
            const statusZh = isInstalled ? '✓' : '(未下载)';
            const statusEn = isInstalled ? '✓' : '(Not downloaded)';
            opt.textContent = `${m.name} ${state.currentLang === 'zh' ? statusZh : statusEn}`;
            opt.dataset.enStr = `${m.name} ${statusEn}`;
            opt.dataset.zhStr = `${m.name} ${statusZh}`;
            opt.dataset.installed = isInstalled;
            opt.dataset.default = m.is_default ? 'true' : 'false';
            
            elements.sttModelSelect.appendChild(opt);
        });

        const defaultOpt = Array.from(elements.sttModelSelect.options)
            .find(opt => opt.dataset.default === 'true');
        if (defaultOpt) {
            elements.sttModelSelect.value = defaultOpt.value;
        }

        // Re-apply language-based model preference (e.g. Parakeet for English)
        onSttLangChange();
        onSttModelChange();
        renderSpeakerIdControls();
    } catch (e) {
        console.error('Failed to load STT models', e);
    }
}

function isSpeakerDiarizationInstalled() {
    return Boolean(state.speakerDiarization && state.speakerDiarization.installed);
}

function renderSpeakerIdControls() {
    if (!elements.sttSpeakerIdToggle) return;

    const uiEnabled = Boolean(state.speakerDiarization && state.speakerDiarization.ui_enabled);
    const container = document.getElementById('stt-speaker-id-setting');
    if (container) {
        container.style.display = uiEnabled ? '' : 'none';
    }
    if (!uiEnabled) {
        elements.sttSpeakerIdToggle.checked = false;
        elements.sttSpeakerIdToggle.disabled = true;
        if (elements.sttSpeakerCountSelect) elements.sttSpeakerCountSelect.disabled = true;
        if (elements.sttSpeakerPresetSelect) elements.sttSpeakerPresetSelect.disabled = true;
        if (elements.sttSpeakerDownloadBtn) elements.sttSpeakerDownloadBtn.style.display = 'none';
        if (elements.sttSpeakerModelProgress) elements.sttSpeakerModelProgress.style.display = 'none';
        return;
    }

    const installed = isSpeakerDiarizationInstalled();
    elements.sttSpeakerIdToggle.disabled = !installed;
    if (!installed) {
        elements.sttSpeakerIdToggle.checked = false;
    }
    if (elements.sttSpeakerCountSelect) {
        elements.sttSpeakerCountSelect.disabled = !installed || !elements.sttSpeakerIdToggle.checked;
    }
    if (elements.sttSpeakerPresetSelect) {
        elements.sttSpeakerPresetSelect.disabled = !installed || !elements.sttSpeakerIdToggle.checked;
    }
    if (elements.sttSpeakerDownloadBtn) {
        elements.sttSpeakerDownloadBtn.style.display = installed ? 'none' : 'inline-flex';
    }
    if (elements.sttSpeakerStatus) {
        if (installed) {
            elements.sttSpeakerStatus.textContent = state.currentLang === 'zh'
                ? '已安装：可为会议转写添加说话人 1/2/3...'
                : 'Installed: can add Speaker 1/2/3... labels to meeting transcripts.';
        } else {
            elements.sttSpeakerStatus.textContent = state.currentLang === 'zh'
                ? '可选下载约 46 MB，本地离线运行。'
                : 'Optional ~46 MB download, runs fully offline.';
        }
    }
}

function onSpeakerIdToggleChange() {
    renderSpeakerIdControls();
}

function onSttModelChange() {
    const opt = elements.sttModelSelect.options[elements.sttModelSelect.selectedIndex];
    if (!opt) return;

    if (opt.dataset.installed === 'true') {
        elements.sttDownloadBtn.style.display = 'none';
        elements.sttTranscribeBtn.disabled = false;
        elements.sttTranscribeBtn.style.opacity = '1';
        elements.sttTranscribeBtn.style.cursor = 'pointer';
    } else {
        elements.sttDownloadBtn.style.display = 'block';
        elements.sttTranscribeBtn.disabled = true;
        elements.sttTranscribeBtn.style.opacity = '0.5';
        elements.sttTranscribeBtn.style.cursor = 'not-allowed';
    }
}

function onSttLangChange() {
    const lang = elements.sttLangSelect.value;
    const opts = Array.from(elements.sttModelSelect.options);
    const selectFirst = (predicate) => {
        const opt = opts.find(predicate);
        if (!opt) return false;
        elements.sttModelSelect.value = opt.value;
        onSttModelChange();
        return true;
    };

    if (lang === 'en') {
        if (selectFirst(opt => opt.value.includes('parakeet') && opt.dataset.installed === 'true')) return;
        if (selectFirst(opt => opt.value.includes('parakeet'))) return;
    }

    if (['auto', 'ja', 'ko', 'yue'].includes(lang)) {
        if (selectFirst(opt => opt.value.includes('sensevoice') && opt.dataset.installed === 'true')) return;
        if (selectFirst(opt => opt.value.includes('sensevoice'))) return;
    }

    if (selectFirst(opt => opt.dataset.default === 'true' && opt.dataset.installed === 'true')) return;
    if (selectFirst(opt => opt.dataset.default === 'true')) return;

    // If preferred model not installed, don't change selection
}

async function downloadSelectedModel() {
    const modelId = elements.sttModelSelect.value;
    if (!modelId) return;
    
    elements.sttDownloadBtn.disabled = true;
    elements.sttModelSelect.disabled = true;
    elements.sttModelProgress.style.display = 'block';
    
    const fill = document.getElementById('model-dl-fill');
    const text = document.getElementById('model-dl-text');
    
    try {
        const response = await fetch('/api/stt/download-model', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model_id: modelId, use_mirror: true })
        });
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const dataStr = line.substring(6).trim();
                    if (!dataStr) continue;
                    const data = JSON.parse(dataStr);
                    
                    if (data.status === 'downloading') {
                        const pct = data.progress != null ? data.progress : 0;
                        fill.style.width = `${pct}%`;
                        let progressLine = state.currentLang === 'zh' && data.message_zh
                            ? data.message_zh
                            : (data.message || `Downloading ${data.file || ''}...`);
                        if (data.file_index != null && data.total_files != null) {
                            progressLine += ` (${data.file_index}/${data.total_files})`;
                        }
                        text.textContent = progressLine;
                    } else if (data.status === 'done') {
                        fill.style.width = '100%';
                        text.textContent = state.currentLang === 'zh' ? '下载完成！' : 'Download Complete!';
                        await loadSttModels(); // refresh dropdown
                        setTimeout(() => {
                            elements.sttModelProgress.style.display = 'none';
                            elements.sttModelSelect.disabled = false;
                            elements.sttDownloadBtn.disabled = false;
                        }, 2000);
                        return;
                    } else if (data.status === 'error') {
                        throw new Error(data.error);
                    }
                }
            }
        }
    } catch (e) {
        const msg = state.currentLang === 'zh' ? '下载失败' : 'Download failed';
        showToast(msg + ': ' + e.message, 'error');
        elements.sttDownloadBtn.disabled = false;
        elements.sttModelSelect.disabled = false;
        elements.sttModelProgress.style.display = 'none';
    }
}

async function downloadSpeakerModel() {
    if (!elements.sttSpeakerDownloadBtn) return;

    elements.sttSpeakerDownloadBtn.disabled = true;
    if (elements.sttSpeakerModelProgress) {
        elements.sttSpeakerModelProgress.style.display = 'block';
    }

    const fill = document.getElementById('speaker-model-dl-fill');
    const text = document.getElementById('speaker-model-dl-text');

    try {
        const response = await fetch('/api/stt/download-speaker-model', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ use_mirror: true })
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const dataStr = line.substring(6).trim();
                if (!dataStr) continue;
                const data = JSON.parse(dataStr);

                if (data.status === 'downloading') {
                    const pct = data.progress != null ? data.progress : 0;
                    if (fill) fill.style.width = `${pct}%`;
                    let progressLine = state.currentLang === 'zh' && data.message_zh
                        ? data.message_zh
                        : (data.message || `Downloading ${data.file || ''}...`);
                    if (data.file_index != null && data.total_files != null) {
                        progressLine += ` (${data.file_index}/${data.total_files})`;
                    }
                    if (text) text.textContent = progressLine;
                } else if (data.status === 'done') {
                    if (fill) fill.style.width = '100%';
                    if (text) text.textContent = state.currentLang === 'zh' ? '说话人模型下载完成！' : 'Speaker ID model downloaded!';
                    await loadSttModels();
                    setTimeout(() => {
                        if (elements.sttSpeakerModelProgress) {
                            elements.sttSpeakerModelProgress.style.display = 'none';
                        }
                        elements.sttSpeakerDownloadBtn.disabled = false;
                    }, 2000);
                    return;
                } else if (data.status === 'error') {
                    throw new Error(data.error);
                }
            }
        }
    } catch (e) {
        const msg = state.currentLang === 'zh' ? '说话人模型下载失败' : 'Speaker ID download failed';
        showToast(msg + ': ' + e.message, 'error');
        elements.sttSpeakerDownloadBtn.disabled = false;
        if (elements.sttSpeakerModelProgress) {
            elements.sttSpeakerModelProgress.style.display = 'none';
        }
    }
}

function clearSttFile(e) {
    if (e) e.stopPropagation();
    state.sttFile = null;
    if (elements.sttFileInput) elements.sttFileInput.value = '';
    elements.sttSelectedFile.style.display = 'none';
    elements.sttUploadZone.style.display = 'block';
    elements.sttResultSection.style.display = 'none';
}

async function startTranscription() {
    if (!state.sttFile) {
        const msg = state.currentLang === 'zh' ? '请先选择文件' : 'Please select a file first';
        showToast(msg, 'error');
        return;
    }
    
    // Check if model is downloaded
    const opt = elements.sttModelSelect.options[elements.sttModelSelect.selectedIndex];
    if (!opt || opt.dataset.installed !== 'true') {
        const msg = state.currentLang === 'zh' ? '请先下载选择的模型' : 'Please download the selected model first';
        showToast(msg, 'error');
        return;
    }
    
    const formData = new FormData();
    formData.append('file', state.sttFile);
    formData.append('language', elements.sttLangSelect.value);
    formData.append('model_id', opt.value);
    const speakerIdEnabled = Boolean(elements.sttSpeakerIdToggle && elements.sttSpeakerIdToggle.checked);
    if (speakerIdEnabled && !isSpeakerDiarizationInstalled()) {
        const msg = state.currentLang === 'zh' ? '请先下载说话人模型' : 'Please download the Speaker ID model first';
        showToast(msg, 'error');
        return;
    }
    formData.append('speaker_id', speakerIdEnabled ? '1' : '0');
    formData.append('speaker_count', elements.sttSpeakerCountSelect ? elements.sttSpeakerCountSelect.value : '-1');
    formData.append('speaker_preset', elements.sttSpeakerPresetSelect ? elements.sttSpeakerPresetSelect.value : 'balanced');
    
    elements.sttTranscribeBtn.style.display = 'none';
    document.getElementById('stt-loading').style.display = 'flex';
    elements.sttResultSection.style.display = 'none';
    elements.sttJobProgress.style.display = 'none';
    elements.sttLiveSegments.innerHTML = '';
    
    try {
        const response = await fetch('/api/stt/transcribe', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        if (data.error) throw new Error(data.error);
        
        state.sttJobId = data.job_id;
        elements.sttJobProgress.style.display = 'block';
        
        pollSttProgress();
    } catch (e) {
        showToast(e.message || 'Error starting transcription', 'error');
        elements.sttTranscribeBtn.style.display = 'flex';
        document.getElementById('stt-loading').style.display = 'none';
    }
}

async function pollSttProgress() {
    if (!state.sttJobId) return;
    
    const eventSource = new EventSource(`/api/stt/progress/${state.sttJobId}`);
    
    eventSource.onmessage = function(event) {
        const dataStr = event.data;
        if (!dataStr) return;
        const data = JSON.parse(dataStr);
        const titleEl = document.getElementById('stt-progress-title');
        
        if (data.status === 'extracting_audio') {
            titleEl.textContent = state.currentLang === 'zh' ? '正在提取音频...' : 'Extracting audio...';
        } else if (data.status === 'loading_model') {
            titleEl.textContent = state.currentLang === 'zh' ? '正在加载模型...' : 'Loading model...';
        } else if (data.status === 'transcribing') {
            titleEl.textContent = state.currentLang === 'zh' ? '正在转写音频...' : 'Transcribing Audio...';
            
            if (data.new_segments && data.new_segments.length > 0) {
                data.new_segments.forEach(seg => {
                    const p = document.createElement('p');
                    p.textContent = formatSttSegment(seg, true);
                    elements.sttLiveSegments.appendChild(p);
                });
                elements.sttLiveSegments.scrollTop = elements.sttLiveSegments.scrollHeight;
            }
        } else if (data.status === 'diarizing') {
            const pct = data.speaker_progress != null ? ` (${data.speaker_progress}%)` : '';
            titleEl.textContent = state.currentLang === 'zh'
                ? `正在识别说话人${pct}...`
                : `Identifying speakers${pct}...`;
        } else if (data.status === 'done') {
            eventSource.close();
            
            // fetch final result
            fetch(`/api/stt/result/${state.sttJobId}`)
                .then(r => r.json())
                .then(res => {
                    elements.sttResultText.value = res.segments.map(s => formatSttSegment(s, false)).join('\n');
                    elements.sttResultSection.style.display = 'block';
                    elements.sttTranscribeBtn.style.display = 'flex';
                    document.getElementById('stt-loading').style.display = 'none';
                    elements.sttJobProgress.style.display = 'none';
                    if (res.speaker_error) {
                        const msg = state.currentLang === 'zh'
                            ? `转写完成，但说话人识别失败：${res.speaker_error}`
                            : `Transcription complete, but Speaker ID failed: ${res.speaker_error}`;
                        showToast(msg, 'info');
                    } else {
                        showToast(state.currentLang === 'zh' ? '转写完成！' : 'Transcription complete!', 'success');
                    }
                });
        } else if (data.status === 'error') {
            eventSource.close();
            showToast(data.error, 'error');
            elements.sttTranscribeBtn.style.display = 'flex';
            document.getElementById('stt-loading').style.display = 'none';
            elements.sttJobProgress.style.display = 'none';
        }
    };
    
    eventSource.onerror = function() {
        eventSource.close();
        // Fallback UI reset
        elements.sttTranscribeBtn.style.display = 'flex';
        document.getElementById('stt-loading').style.display = 'none';
    };
}

function formatTime(seconds) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
}

function formatSpeakerLabel(seg) {
    if (!seg || seg.speaker === undefined || seg.speaker === null) return '';
    const n = Number(seg.speaker) + 1;
    return state.currentLang === 'zh' ? `说话人 ${n}` : `Speaker ${n}`;
}

function formatSttSegment(seg, includeTime) {
    const speaker = formatSpeakerLabel(seg);
    const speakerPrefix = speaker ? `${speaker}: ` : '';
    const timePrefix = includeTime ? `[${formatTime(seg.start)} - ${formatTime(seg.end)}] ` : '';
    return `${timePrefix}${speakerPrefix}${seg.text || ''}`;
}

function exportTranscription() {
    if (!state.sttJobId) return;
    const format = document.getElementById('stt-export-format').value;
    window.location.href = `/api/stt/export/${state.sttJobId}?format=${format}&lang=${state.currentLang}`;
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
}

function showSttFileInfo(file) {
    elements.sttFilenameDisplay.textContent = file.name;
    const sizeEl = document.getElementById('stt-filesize-display');
    if (sizeEl) sizeEl.textContent = formatFileSize(file.size);
    elements.sttUploadZone.style.display = 'none';
    elements.sttSelectedFile.style.display = 'flex';
}

function copySttResult() {
    const textarea = document.getElementById('stt-result-text');
    if (!textarea || !textarea.value) return;
    navigator.clipboard.writeText(textarea.value).then(() => {
        const msg = state.currentLang === 'zh' ? '已复制到剪贴板' : 'Copied to clipboard';
        showToast(msg, 'success');
    }).catch(() => {
        textarea.select();
        document.execCommand('copy');
        const msg = state.currentLang === 'zh' ? '已复制到剪贴板' : 'Copied to clipboard';
        showToast(msg, 'success');
    });
}
