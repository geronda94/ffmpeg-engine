import whisper
import logging

logger = logging.getLogger(__name__)

class WhisperAgent:
    def __init__(self, model_name="base"):
        self.model_name = model_name
        self._model = None

    @property
    def model(self):
        if self._model is None:
            logger.info(f"Loading Whisper model ({self.model_name})...")
            self._model = whisper.load_model(self.model_name)
        return self._model

    def transcribe(self, audio_path, language=None, word_timestamps=True):
        """
        Транскрибирует аудио с поддержкой пословных таймингов.
        """
        transcribe_kwargs = {
            "verbose": False,
            "word_timestamps": word_timestamps
        }
        if language:
            transcribe_kwargs["language"] = language
            
        logger.info(f"Transcribing {audio_path} (word_timestamps={word_timestamps})...")
        result = self.model.transcribe(audio_path, **transcribe_kwargs)
        return result.get('segments', [])
