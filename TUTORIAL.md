# 🎓 Picobot Tutorial

Welcome to the Picobot tutorial.

This guide walks you through the main capabilities of the system.

------------------------------------------------------------------------

# 🚀 Starting Picobot

Launch the assistant:

    make start

You should see the CLI prompt.

------------------------------------------------------------------------

# 📚 Getting Help

    /help

Lists available commands.

------------------------------------------------------------------------

# 💬 Chat

You can talk normally:

    Hello Picobot

The router will send the request to the chat workflow.

------------------------------------------------------------------------

# 🔊 Text to Speech

Generate spoken audio:

    /tts Hello world

Output example:

    .picobot/workspace/outputs/tts/tts_output_xxx.wav

------------------------------------------------------------------------

# 🎙 Speech to Text

Transcribe audio:

    /stt audio.wav

Tip:

Audio should ideally be 16 kHz WAV.

------------------------------------------------------------------------

# 📺 YouTube Transcript

Extract transcript and summary:

    /yt https://youtube.com/watch?v=VIDEO_ID

Steps performed:

1.  download subtitles
2.  clean transcript
3.  summarize

------------------------------------------------------------------------

# 🐍 Python Execution

Run Python inside the sandbox:

    /python print(2+2)

Output:

    4

------------------------------------------------------------------------

# 🌐 Web Fetch

Retrieve webpage content:

    /fetch https://example.com

------------------------------------------------------------------------

# 🎙 Podcast Generation

Generate narrated podcast content.

    /podcast explain black holes

Pipeline:

LLM → script → TTS → audio

------------------------------------------------------------------------

# 🔍 Debug Mode

Debug mode shows internal steps.

    make start

You will see:

-   routing decisions
-   tool execution
-   memory updates

------------------------------------------------------------------------

# 🧰 Useful Commands

    /status
    /tools

------------------------------------------------------------------------

# 🐳 Sandbox Shell

Open a shell inside the runtime container:

    make sandbox-shell

------------------------------------------------------------------------

# 🧪 Troubleshooting

Check tool status:

    make tools-doctor

Rebuild sandbox:

    make sandbox-rebuild

------------------------------------------------------------------------

# 🎉 Next Steps

Explore:

-   podcast generation
-   YouTube summarization
-   tool extensions

Picobot is designed to grow with your workflows.
