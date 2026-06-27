let network = null;
let nodesDataset = new vis.DataSet([]);
let edgesDataset = new vis.DataSet([]);

// Colors matching our CSS variables
const COLORS = {
    File: '#06b6d4',
    Class: '#d946ef',
    Function: '#10b981',
    Table: '#f59e0b',
    API: '#f43f5e'
};

document.addEventListener("DOMContentLoaded", () => {
    initGraph();
    reloadGraph();
});

// Initialize Vis.js Network Graph
function initGraph() {
    const container = document.getElementById("network-graph");

    const data = {
        nodes: nodesDataset,
        edges: edgesDataset
    };

    const options = {
        nodes: {
            font: {
                color: '#ffffff',
                size: 14,
                face: 'Outfit'
            },
            borderWidth: 2,
            shadow: true
        },
        edges: {
            color: {
                color: 'rgba(255, 255, 255, 0.2)',
                highlight: '#6366f1',
                hover: '#06b6d4'
            },
            width: 1.5,
            selectionWidth: 3,
            arrows: {
                to: { enabled: true, scaleFactor: 0.8 }
            },
            font: {
                size: 10,
                color: '#9ca3af',
                face: 'Outfit',
                align: 'middle'
            },
            smooth: {
                enabled: true,
                type: 'dynamic',
                roundness: 0.5
            }
        },
        groups: {
            File: {
                color: { background: COLORS.File, border: '#0891b2', highlight: { background: '#22d3ee', border: '#0891b2' } },
                shape: 'box',
                margin: 10
            },
            Class: {
                color: { background: COLORS.Class, border: '#c084fc', highlight: { background: '#f5d0fe', border: '#c084fc' } },
                shape: 'ellipse',
                margin: 8
            },
            Function: {
                color: { background: COLORS.Function, border: '#059669', highlight: { background: '#34d399', border: '#059669' } },
                shape: 'dot',
                size: 16
            },
            Table: {
                color: { background: COLORS.Table, border: '#d97706', highlight: { background: '#fde047', border: '#d97706' } },
                shape: 'database',
                size: 20
            },
            API: {
                color: { background: COLORS.API, border: '#e11d48', highlight: { background: '#fda4af', border: '#e11d48' } },
                shape: 'diamond',
                size: 18
            }
        },
        physics: {
            enabled: true,
            barnesHut: {
                gravitationalConstant: -2000,
                centralGravity: 0.3,
                springLength: 150,
                springConstant: 0.04,
                damping: 0.09,
                avoidOverlap: 0.5
            },
            stabilization: {
                enabled: true,
                iterations: 150,
                updateInterval: 25
            }
        },
        interaction: {
            hover: true,
            tooltipDelay: 200,
            hideEdgesOnDrag: false
        }
    };

    network = new vis.Network(container, data, options);

    // Stop physics after stabilization to prevent endless oscillation/CPU use
    network.on("stabilizationIterationsDone", function () {
        network.setOptions({ physics: { enabled: false } });
        console.log("[Graph] Physics paused (stabilized)");
    });
}

// Reload Graph data from FastAPI
async function reloadGraph() {
    try {
        const response = await fetch("/api/graph");
        if (!response.ok) throw new Error("Failed to load graph data");
        const data = await response.json();

        // Update dataset
        nodesDataset.clear();
        edgesDataset.clear();

        nodesDataset.add(data.nodes);
        edgesDataset.add(data.edges);

        // Re-enable physics to let nodes arrange nicely, then stabilize
        network.setOptions({ physics: { enabled: true } });
        network.stabilize();
        console.log(`[Graph] Loaded ${data.nodes.length} nodes, ${data.edges.length} edges.`);
    } catch (e) {
        console.error("Error reloading graph:", e);
    }
}

// Center/fit and stabilize graph
function stabilizeGraph() {
    network.setOptions({ physics: { enabled: true } });
    network.stabilize();
}

// Handle Chat Message Sending
async function sendMessage() {
    const input = document.getElementById("chat-input");
    const text = input.value.trim();
    if (!text) return;

    input.value = "";
    appendMessage("user", text);

    // Create assistant message container for streaming
    const msgId = appendMessage("assistant", "Thinking...");
    const bubble = document.getElementById(msgId).querySelector(".message-bubble");

    try {
        const response = await fetch("/api/chat", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ message: text })
        });

        if (!response.ok) {
            bubble.textContent = "Error communicating with server.";
            return;
        }

        // Clean loading message
        bubble.innerHTML = "";

        // Read response stream
        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");

        let networkBuffer = ""; // Holds incoming raw data lines
        let aiMarkdownText = ""; // Holds ONLY clean aggregated text for Marked

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            // 1. Decode current network packet chunks
            networkBuffer += decoder.decode(value, { stream: true });

            // 2. Process complete individual lines split by \n
            const lines = networkBuffer.split("\n");

            // Save the last incomplete line fragment back to the network buffer
            networkBuffer = lines.pop();

            for (const line of lines) {
                const cleanedLine = line.trim();
                if (!cleanedLine || !cleanedLine.startsWith("data:")) continue;

                const dataContent = cleanedLine.replace("data:", "").trim();
                if (dataContent === "[DONE]") break;

                try {
                    const parsed = JSON.parse(dataContent);
                    if (parsed.text) {
                        // Accumulate only the pure content string
                        aiMarkdownText += parsed.text;
                    }
                } catch (err) {
                    // Ignore transient or partial JSON parse drops
                }
            }

            // 3. Render clean markdown content using Marked
            bubble.innerHTML = marked.parse(aiMarkdownText);

            // Scroll to bottom of chat
            const chatMessages = document.getElementById("chat-messages");
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    } catch (e) {
        console.error("Chat error:", e);
        bubble.textContent = "A connection error occurred.";
    }
}

function handleKeyPress(e) {
    if (e.key === "Enter") {
        sendMessage();
    }
}

// Append message bubble to UI
function appendMessage(sender, text) {
    const chatMessages = document.getElementById("chat-messages");
    const msgId = "msg-" + Date.now();

    const msgDiv = document.createElement("div");
    msgDiv.className = `message ${sender}`;
    msgDiv.id = msgId;

    const senderSpan = document.createElement("span");
    senderSpan.className = "message-sender";
    senderSpan.textContent = sender === "user" ? "You" : "Graph RAG AI";

    const bubbleDiv = document.createElement("div");
    bubbleDiv.className = "message-bubble";
    bubbleDiv.innerHTML = sender === "assistant" ? marked.parse(text) : escapeHtml(text);

    msgDiv.appendChild(senderSpan);
    msgDiv.appendChild(bubbleDiv);
    chatMessages.appendChild(msgDiv);

    chatMessages.scrollTop = chatMessages.scrollHeight;
    return msgId;
}

function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, function (m) { return map[m]; });
}
