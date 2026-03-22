// Chart.js default configuration for ComplyChip
const chartColors = {
    primary: '#4f46e5',
    primaryLight: 'rgba(79, 70, 229, 0.1)',
    success: '#059669',
    successLight: 'rgba(5, 150, 105, 0.1)',
    warning: '#d97706',
    warningLight: 'rgba(217, 119, 6, 0.1)',
    danger: '#dc2626',
    dangerLight: 'rgba(220, 38, 38, 0.1)',
    info: '#2563eb',
    infoLight: 'rgba(37, 99, 235, 0.1)',
    gray: '#94a3b8',
    grayLight: 'rgba(148, 163, 184, 0.1)',
    palette: ['#4f46e5', '#059669', '#d97706', '#dc2626', '#2563eb', '#7c3aed', '#0891b2', '#c026d3']
};

// Apply global Chart.js defaults
if (typeof Chart !== 'undefined') {
    Chart.defaults.font.family = "'Inter', sans-serif";
    Chart.defaults.font.size = 12;
    Chart.defaults.color = '#64748b';
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    Chart.defaults.plugins.legend.labels.pointStyleWidth = 8;
    Chart.defaults.plugins.legend.labels.padding = 16;
    Chart.defaults.plugins.tooltip.backgroundColor = '#1a1b23';
    Chart.defaults.plugins.tooltip.titleFont = { size: 12, weight: 600 };
    Chart.defaults.plugins.tooltip.bodyFont = { size: 11 };
    Chart.defaults.plugins.tooltip.padding = 10;
    Chart.defaults.plugins.tooltip.cornerRadius = 8;
    Chart.defaults.plugins.tooltip.displayColors = true;
    Chart.defaults.plugins.tooltip.boxPadding = 4;
    Chart.defaults.elements.line.tension = 0.35;
    Chart.defaults.elements.line.borderWidth = 2;
    Chart.defaults.elements.point.radius = 3;
    Chart.defaults.elements.point.hoverRadius = 5;
    Chart.defaults.elements.bar.borderRadius = 4;
    Chart.defaults.scale.grid = { color: 'rgba(226, 232, 240, 0.5)', drawBorder: false };
}

// Create a line chart
function createLineChart(canvasId, labels, datasets, options = {}) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;
    return new Chart(ctx, {
        type: 'line',
        data: { labels, datasets: datasets.map((ds, i) => ({
            borderColor: ds.color || chartColors.palette[i],
            backgroundColor: ds.bgColor || (ds.color || chartColors.palette[i]).replace(')', ', 0.1)').replace('rgb', 'rgba'),
            fill: ds.fill !== undefined ? ds.fill : true,
            pointBackgroundColor: ds.color || chartColors.palette[i],
            ...ds
        }))},
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: datasets.length > 1 } },
            scales: { y: { beginAtZero: options.beginAtZero !== false, ...options.yScale }, x: { ...options.xScale } },
            ...options
        }
    });
}

// Create a bar chart
function createBarChart(canvasId, labels, datasets, options = {}) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;
    return new Chart(ctx, {
        type: 'bar',
        data: { labels, datasets: datasets.map((ds, i) => ({
            backgroundColor: ds.color || chartColors.palette[i],
            borderRadius: 4,
            barPercentage: 0.6,
            ...ds
        }))},
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: datasets.length > 1 } },
            scales: { y: { beginAtZero: true, ...options.yScale }, x: { ...options.xScale } },
            ...options
        }
    });
}

// Create a doughnut/pie chart
function createDoughnutChart(canvasId, labels, data, options = {}) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;
    return new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels,
            datasets: [{
                data,
                backgroundColor: options.colors || chartColors.palette.slice(0, data.length),
                borderWidth: 0,
                hoverOffset: 4,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: options.cutout || '70%',
            plugins: {
                legend: { position: options.legendPosition || 'bottom', labels: { padding: 16 } }
            },
            ...options
        }
    });
}

// Create a radar chart
function createRadarChart(canvasId, labels, datasets, options = {}) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;
    return new Chart(ctx, {
        type: 'radar',
        data: { labels, datasets: datasets.map((ds, i) => ({
            borderColor: ds.color || chartColors.palette[i],
            backgroundColor: (ds.color || chartColors.palette[i]).replace(')', ', 0.15)').replace('rgb', 'rgba'),
            pointBackgroundColor: ds.color || chartColors.palette[i],
            borderWidth: 2,
            ...ds
        }))},
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: { r: { beginAtZero: true, max: 100, ticks: { stepSize: 20, display: false }, grid: { color: 'rgba(226, 232, 240, 0.3)' }, pointLabels: { font: { size: 11 } } } },
            ...options
        }
    });
}
