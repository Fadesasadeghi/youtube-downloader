"""Audio backend tests: synthetic metadata and temporary files only."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from yt_dlp import YoutubeDL
from yt_dlp.postprocessor.ffmpeg import FFmpegExtractAudioPP
from yt_dlp.utils import DownloadError, PostProcessingError

from src.downloader import download_audio


class AudioDownloadTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.filepath = self.directory / 'final [test].mp3'
        patcher = patch('src.downloader.yt_dlp.YoutubeDL')
        self.factory = patcher.start()
        self.addCleanup(patcher.stop)
        self.ydl = self.factory.return_value.__enter__.return_value
        self.ydl.extract_info.return_value = {'id': 'test', 'title': 'Example'}
        self.ydl.process_ie_result.side_effect = self.finish

    def finish(self, info, download):
        self.assertTrue(download)
        if not self.filepath.exists():
            self.filepath.write_bytes(b'mock audio')
        self.ydl.add_post_processor.call_args.args[0].run({
            **info, 'filepath': str(self.filepath), 'ext': self.filepath.suffix[1:]})
        return {**info, 'filepath': 'stale.webm'}

    def options(self, audio_format='mp3'):
        self.filepath = self.directory / f'final [test].{audio_format.lower()}'
        result = download_audio(' test ', self.directory, audio_format)
        return self.factory.call_args.args[0], result

    def test_mp3_options_and_final_path(self):
        options, result = self.options()
        self.assertEqual(options['format'], 'bestaudio')
        self.assertEqual(options['postprocessors'], [
            {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}])
        self.assertEqual(options['final_ext'], 'mp3')
        for option in ('quiet', 'no_warnings', 'noplaylist', 'restrictfilenames', 'windowsfilenames'):
            self.assertTrue(options[option])
        self.assertFalse(options['overwrites'])
        self.assertEqual(options['js_runtimes'], {'node': {'path': '/usr/bin/node'}})
        self.assertEqual(options['outtmpl'], '%(title).150B [%(id)s] [audio-mp3].%(ext)s')
        self.assertEqual(options['paths'], {'home': str(self.directory)})
        self.ydl.extract_info.assert_called_once_with('test', download=False, process=False)
        self.assertEqual(self.ydl.add_post_processor.call_args.kwargs, {'when': 'after_move'})
        self.assertEqual(result, {'filepath': str(self.filepath), 'id': 'test',
                                 'title': 'Example', 'ext': 'mp3', 'audio_format': 'mp3'})
        self.assertTrue(Path(result['filepath']).is_absolute())
        self.assertTrue(Path(result['filepath']).is_file())

    def test_m4a_options_and_case_normalization(self):
        options, result = self.options('M4A')
        self.assertEqual(options['format'],
                         'bestaudio[ext=m4a]/bestaudio[acodec^=aac]/bestaudio[acodec^=mp4a]/bestaudio')
        self.assertEqual(options['postprocessors'], [
            {'key': 'FFmpegExtractAudio', 'preferredcodec': 'm4a'}])
        self.assertEqual(options['final_ext'], 'm4a')
        self.assertIn('[audio-m4a]', options['outtmpl'])
        self.assertEqual(result['audio_format'], 'm4a')
        self.assertEqual(result['ext'], 'm4a')
        self.assertEqual(self.options('MP3')[1]['audio_format'], 'mp3')

    def test_creates_nested_directory(self):
        destination = self.directory / 'new' / 'nested'
        self.filepath = destination / 'final.mp3'
        download_audio('test', str(destination))
        self.assertTrue(destination.is_dir())

    def test_invalid_inputs_before_downloader_initialization(self):
        for url in ('', '  ', None, 3, b'url'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                download_audio(url, self.directory)
        for audio_format in ('wav', '', ' mp3 ', None, 3, b'mp3'):
            with self.subTest(audio_format=audio_format), self.assertRaises(ValueError):
                download_audio('test', self.directory, audio_format)
        self.filepath.touch()
        for directory in (None, '', '  ', 3, b'path', 'bad\x00path', self.filepath):
            with self.subTest(directory=directory), self.assertRaises(ValueError):
                download_audio('test', directory)
        self.factory.assert_not_called()

    def test_extraction_download_and_postprocessing_errors_are_safe(self):
        for method in (self.ydl.extract_info, self.ydl.process_ie_result):
            original = method.side_effect
            for error in (DownloadError('https://user:secret@example.invalid/?token=secret'),
                          PostProcessingError('secret'), OSError('secret')):
                method.side_effect = error
                with self.subTest(error=type(error)), self.assertRaises(RuntimeError) as raised:
                    download_audio('test', self.directory)
                self.assertNotIn('secret', str(raised.exception))
                self.assertIn(type(error).__name__, str(raised.exception))
                self.assertTrue(raised.exception.__suppress_context__)
            method.side_effect = original

    def test_rejects_empty_and_multi_entry_results_before_download(self):
        for info in (None, {}, [], {'_type': 'playlist'}, {'_type': 'multi_video'},
                     {'entries': []}, {'_type': 'url'}):
            self.ydl.extract_info.return_value = info
            with self.subTest(info=info), self.assertRaises(RuntimeError):
                download_audio('test', self.directory)
        self.ydl.process_ie_result.assert_not_called()

    def test_missing_final_path(self):
        self.ydl.process_ie_result.side_effect = None
        with self.assertRaisesRegex(RuntimeError, 'completed output file path'):
            download_audio('test', self.directory)
        self.ydl.process_ie_result.side_effect = lambda *a, **k: self.ydl.add_post_processor.call_args.args[0].run({'id': 'test'})
        with self.assertRaisesRegex(RuntimeError, 'completed output file path'):
            download_audio('test', self.directory)

    def test_missing_final_file_and_directory_instead_of_file(self):
        for path in (self.filepath, self.directory):
            self.ydl.process_ie_result.side_effect = lambda *a, **k: self.ydl.add_post_processor.call_args.args[0].run({'filepath': str(path)})
            with self.subTest(path=path), self.assertRaisesRegex(RuntimeError, 'could not be found'):
                download_audio('test', self.directory)

    def test_wrong_final_extension(self):
        self.filepath = self.directory / 'unconverted.webm'
        with self.assertRaisesRegex(RuntimeError, 'unexpected format'):
            download_audio('test', self.directory)

    def test_filesystem_failures(self):
        for operation in ('mkdir', 'resolve'):
            with patch(f'src.downloader.Path.{operation}', side_effect=PermissionError('secret')):
                with self.assertRaises(RuntimeError) as raised:
                    download_audio('test', self.directory)
                self.assertNotIn('secret', str(raised.exception))
        self.factory.assert_not_called()

    def test_real_selectors_with_synthetic_metadata(self):
        def audio(identifier, ext, codec):
            return {'format_id': identifier, 'url': 'https://example.invalid/media',
                    'ext': ext, 'acodec': codec, 'vcodec': 'none'}
        native = audio('native', 'm4a', 'mp4a.40.2')
        aac = audio('aac', 'aac', 'aac')
        mp4a = audio('mp4a', 'mp4', 'mp4a.40.2')
        opus = audio('opus', 'webm', 'opus')
        combined = {**opus, 'format_id': 'combined', 'vcodec': 'vp9'}
        for target, formats, expected in (
            ('mp3', [native, opus, combined], 'opus'),
            ('m4a', [native, opus, combined], 'native'),
            ('m4a', [aac, opus], 'aac'),
            ('m4a', [mp4a, opus], 'mp4a'),
            ('m4a', [opus], 'opus'),
            ('mp3', [combined], None),
        ):
            options, _ = self.options(target)
            with YoutubeDL(options) as ydl:
                selected = list(ydl.build_format_selector(options['format'])({
                    'formats': formats, 'has_merged_format': False, 'incomplete_formats': False}))
            with self.subTest(target=target, expected=expected):
                self.assertEqual([item['format_id'] for item in selected], [expected] if expected else [])

    def test_real_postprocessor_native_m4a_skips_conversion(self):
        with YoutubeDL({'quiet': True}) as ydl:
            pp = FFmpegExtractAudioPP(ydl, preferredcodec='m4a')
            with patch.object(pp, 'get_audio_codec', return_value='aac'), patch.object(pp, 'run_ffmpeg') as ffmpeg:
                _, info = pp.run({'filepath': str(self.directory / 'native.m4a'), 'ext': 'm4a'})
                ffmpeg.assert_not_called()
                self.assertEqual(info['ext'], 'm4a')

    def test_real_postprocessor_conversion_and_aac_copy(self):
        for target, source_codec, source_ext, expected_codec in (
            ('mp3', 'opus', 'webm', 'libmp3lame'),
            ('m4a', 'aac', 'aac', 'copy'),
            ('m4a', 'opus', 'webm', 'aac'),
        ):
            source = self.directory / f'input.{source_ext}'
            source.write_bytes(b'synthetic input')
            with YoutubeDL({'quiet': True}) as ydl:
                pp = FFmpegExtractAudioPP(ydl, preferredcodec=target)
                # Bypass FFmpeg/ffprobe entirely while exercising yt-dlp's
                # codec decision and final metadata update.
                pp._features = {}
                def convert(path, output, codec, options):
                    self.assertEqual(codec, expected_codec)
                    Path(output).write_bytes(b'synthetic output')
                with patch.object(pp, 'get_audio_codec', return_value=source_codec), \
                     patch.object(pp, 'run_ffmpeg', side_effect=convert) as ffmpeg:
                    _, result = pp.run({'filepath': str(source), 'ext': source_ext})
                ffmpeg.assert_called_once()
                self.assertEqual(result['ext'], target)
                self.assertEqual(Path(result['filepath']).suffix, f'.{target}')
                self.assertTrue(Path(result['filepath']).is_file())

    def test_existing_completed_output_with_real_ytdlp_pipeline(self):
        for target in ('mp3', 'm4a'):
            options, _ = self.options(target)
            info = {'id': 'existing', 'title': 'Existing', 'extractor': 'mock',
                    'webpage_url': 'https://example.invalid/watch',
                    'formats': [{'format_id': 'opus', 'url': 'https://example.invalid/media',
                                 'ext': 'webm', 'acodec': 'opus', 'vcodec': 'none'}]}
            final = self.directory / f'Existing [existing] [audio-{target}].{target}'
            final.write_bytes(b'existing audio')
            # Use real processing/filename detection, but forbid any network download.
            with patch('src.downloader.yt_dlp.YoutubeDL', YoutubeDL), \
                 patch.object(YoutubeDL, 'extract_info', return_value=info), \
                 patch.object(YoutubeDL, 'dl', side_effect=AssertionError('Unexpected download')), \
                 patch.object(FFmpegExtractAudioPP, 'get_audio_codec', return_value=target if target == 'mp3' else 'aac'), \
                 patch.object(FFmpegExtractAudioPP, 'run_ffmpeg', side_effect=AssertionError('Unexpected conversion')):
                result = download_audio('test', self.directory, target)
            self.assertEqual(result['filepath'], str(final))
            self.assertEqual(final.read_bytes(), b'existing audio')


if __name__ == '__main__':
    unittest.main()
