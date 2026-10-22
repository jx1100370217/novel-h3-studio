import copy
import unittest

from novel_h3.v2.audio_anchor import (
    add_audio_anchor, audio_vae_roundtrip_graph, validate_target_audio,
)


class CinemaAudioAnchorTests(unittest.TestCase):
    def graph(self):
        return {
            '1': {'class_type': 'UNETLoader', 'inputs': {'unet_name': 'h3_ref2va.safetensors'}},
            '4': {'class_type': 'VAELoader', 'inputs': {'vae_name': 'h3_audio_vae.safetensors'}},
            '6': {'class_type': 'MiniMaxH3ReferenceToVideo', 'inputs': {'prompt': 'native H3 shot'}},
            '13': {'class_type': 'SamplerCustomAdvanced', 'inputs': {'latent_image': ['6', 1]}},
            '16': {'class_type': 'VAEDecodeAudio', 'inputs': {'samples': ['13', 0], 'vae': ['4', 0]}},
        }

    def test_full_target_audio_enters_h3_sampling_instead_of_postdub(self):
        nodes = self.graph()
        original = copy.deepcopy(nodes)
        latent, record = add_audio_anchor(nodes, staged_audio_name='cinema/target.wav',
                                          frames=175, target_duration_seconds=7.3)
        self.assertEqual(latent, ['304', 0])
        self.assertEqual(nodes['301']['inputs'], {'audio': ['300', 0], 'vae': ['4', 0]})
        self.assertEqual(nodes['302']['inputs'], {'value': 0.0, 'width': 1, 'height': 1})
        self.assertEqual(nodes['303']['inputs'], {'samples': ['301', 0], 'mask': ['302', 0]})
        self.assertEqual(nodes['304']['inputs'], {'video_latent': ['6', 1], 'audio_latent': ['303', 0]})
        for key in original:
            self.assertEqual(nodes[key], original[key])
        # The caller connects the conditioned latent before the H3 sampling step.
        nodes['13']['inputs']['latent_image'] = latent
        self.assertEqual(nodes['16']['inputs']['samples'], ['13', 0])
        self.assertEqual(record['audio_route'], 'h3_audio_conditioned')
        self.assertTrue(record['target_audio_used_during_video_sampling'])
        self.assertFalse(record['postdub'])
        self.assertFalse(record['quality_verified'])
        self.assertFalse(record['waveform_bit_exact'])
        self.assertEqual(record['target_audio_latent_frames'], 292)
        self.assertEqual({nodes[key]['class_type'] for key in set(nodes) - set(original)},
                         {'LoadAudio', 'VAEEncodeAudio', 'SolidMask', 'SetLatentNoiseMask', 'LTXVConcatAVLatent'})

    def test_target_duration_covers_snapped_generation_not_requested_seconds(self):
        nodes = self.graph()
        original = copy.deepcopy(nodes)
        # An authored 7s request becomes 175 frames / 7.291667s.
        with self.assertRaisesRegex(ValueError, 'complete generated clip'):
            add_audio_anchor(nodes, staged_audio_name='target.wav', frames=175, target_duration_seconds=7.0)
        self.assertEqual(nodes, original)
        self.assertEqual(validate_target_audio(175, 175 / 24), 175 / 24)
        for seconds in [-1, float('nan'), float('inf'), True]:
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                validate_target_audio(175, seconds)

    def test_incompatible_frame_grid_or_input_path_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '17k'):
            validate_target_audio(168, 7.0)
        for name in ['/tmp/target.wav', '../target.wav', 'target.mp3']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                add_audio_anchor(self.graph(), staged_audio_name=name, frames=175, target_duration_seconds=8)

    def test_id_collision_does_not_modify_original_graph(self):
        nodes = self.graph()
        original = copy.deepcopy(nodes)
        with self.assertRaisesRegex(ValueError, 'collide'):
            add_audio_anchor(nodes, staged_audio_name='target.wav', frames=175,
                             target_duration_seconds=8, first_node_id=1)
        self.assertEqual(nodes, original)

    def test_roundtrip_uses_actual_h3_audio_vae_and_has_no_video_or_tts(self):
        nodes, record = audio_vae_roundtrip_graph(
            'cinema/target.wav', 'minimax_h3_audio_vae_fp32.safetensors', 'cinema/roundtrip/test')
        self.assertEqual(nodes['1']['inputs']['vae_name'], 'minimax_h3_audio_vae_fp32.safetensors')
        self.assertEqual(nodes['3']['inputs'], {'audio': ['2', 0], 'vae': ['1', 0]})
        self.assertEqual(nodes['4']['inputs'], {'samples': ['3', 0], 'vae': ['1', 0]})
        self.assertEqual(nodes['5']['inputs']['audio'], ['4', 0])
        self.assertEqual({node['class_type'] for node in nodes.values()},
                         {'VAELoader', 'LoadAudio', 'VAEEncodeAudio', 'VAEDecodeAudio', 'SaveAudio'})
        self.assertFalse(record['video_generated'])
        self.assertFalse(record['quality_verified'])
        self.assertEqual(record['av_sync_review']['status'], 'not_evaluated')


if __name__ == '__main__':
    unittest.main()
