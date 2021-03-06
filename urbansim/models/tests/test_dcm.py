import numpy as np
import numpy.testing as npt
import pandas as pd
import pytest
import os
import tempfile
import yaml
from pandas.util import testing as pdt

from ...utils import testing

from .. import dcm


@pytest.fixture
def seed(request):
    current = np.random.get_state()

    def fin():
        np.random.set_state(current)
    request.addfinalizer(fin)

    np.random.seed(0)


@pytest.fixture
def choosers():
    return pd.DataFrame(
        {'var1': range(5, 10),
         'thing_id': ['a', 'c', 'e', 'g', 'i']})


@pytest.fixture
def grouped_choosers(choosers):
    choosers['group'] = ['x', 'y', 'x', 'x', 'y']
    return choosers


@pytest.fixture
def alternatives():
    return pd.DataFrame(
        {'var2': range(10, 20),
         'var3': range(20, 30)},
        index=pd.Index([x for x in 'abcdefghij'], name='thing_id'))


@pytest.fixture
def basic_dcm():
    model_exp = 'var2 + var1:var3'
    sample_size = 5
    probability_mode = 'full_product'
    choice_mode = 'individual'
    choosers_fit_filters = ['var1 != 5']
    choosers_predict_filters = ['var1 != 7']
    alts_fit_filters = ['var3 != 15']
    alts_predict_filters = ['var2 != 14']
    interaction_predict_filters = None
    estimation_sample_size = None
    choice_column = None
    name = 'Test LCM'

    model = dcm.MNLDiscreteChoiceModel(
        model_exp, sample_size,
        probability_mode, choice_mode,
        choosers_fit_filters, choosers_predict_filters,
        alts_fit_filters, alts_predict_filters,
        interaction_predict_filters, estimation_sample_size,
        choice_column, name)

    return model


@pytest.fixture
def basic_dcm_fit(basic_dcm, choosers, alternatives):
    basic_dcm.fit(choosers, alternatives, choosers.thing_id)
    return basic_dcm


def test_unit_choice_uniform(choosers, alternatives):
    probabilities = [1] * len(alternatives)
    choices = dcm.unit_choice(
        choosers.index, alternatives.index, probabilities)
    npt.assert_array_equal(choices.index, choosers.index)
    assert choices.isin(alternatives.index).all()


def test_unit_choice_some_zero(choosers, alternatives):
    probabilities = [0, 1, 0, 1, 1, 0, 1, 0, 0, 1]
    choices = dcm.unit_choice(
        choosers.index, alternatives.index, probabilities)
    npt.assert_array_equal(choices.index, choosers.index)
    npt.assert_array_equal(sorted(choices.values), ['b', 'd', 'e', 'g', 'j'])


def test_unit_choice_not_enough(choosers, alternatives):
    probabilities = [0, 0, 0, 0, 0, 1, 0, 1, 0, 0]
    choices = dcm.unit_choice(
        choosers.index, alternatives.index, probabilities)
    npt.assert_array_equal(choices.index, choosers.index)
    assert choices.isnull().sum() == 3
    npt.assert_array_equal(sorted(choices[~choices.isnull()]), ['f', 'h'])


def test_unit_choice_none_available(choosers, alternatives):
    probabilities = [0] * len(alternatives)
    choices = dcm.unit_choice(
        choosers.index, alternatives.index, probabilities)
    npt.assert_array_equal(choices.index, choosers.index)
    assert choices.isnull().all()


def test_mnl_dcm(seed, basic_dcm, choosers, alternatives):
    assert basic_dcm.choosers_columns_used() == ['var1']
    assert set(basic_dcm.alts_columns_used()) == {'var2', 'var3'}
    assert set(basic_dcm.interaction_columns_used()) == \
        {'var1', 'var2', 'var3'}
    assert set(basic_dcm.columns_used()) == {'var1', 'var2', 'var3'}

    loglik = basic_dcm.fit(choosers, alternatives, choosers.thing_id)
    basic_dcm.report_fit()

    # hard to test things exactly because there's some randomness
    # involved, but can at least do a smoke test.
    assert len(loglik) == 3
    assert len(basic_dcm.fit_parameters) == 2
    assert len(basic_dcm.fit_parameters.columns) == 3

    filtered_choosers, filtered_alts = basic_dcm.apply_predict_filters(
        choosers, alternatives)

    probs = basic_dcm.probabilities(choosers, alternatives)
    assert len(probs) == len(filtered_choosers) * len(filtered_alts)

    sprobs = basic_dcm.summed_probabilities(choosers, alternatives)
    assert len(sprobs) == len(filtered_alts)
    npt.assert_allclose(sprobs.sum(), len(filtered_choosers))

    choices = basic_dcm.predict(choosers.iloc[1:], alternatives)

    pdt.assert_series_equal(
        choices,
        pd.Series(['h', 'c', 'f'], index=[1, 3, 4]))

    # check that we can do a YAML round-trip
    yaml_str = basic_dcm.to_yaml()
    new_model = dcm.MNLDiscreteChoiceModel.from_yaml(yaml_str)

    assert new_model.fitted
    testing.assert_frames_equal(
        basic_dcm.fit_parameters, new_model.fit_parameters)


def test_mnl_dcm_repeated_alts(basic_dcm, choosers, alternatives):
    interaction_predict_filters = ['var1 * var2 > 50']
    choice_column = 'thing_id'

    basic_dcm.interaction_predict_filters = interaction_predict_filters
    basic_dcm.choice_column = choice_column

    loglik = basic_dcm.fit(choosers, alternatives, 'thing_id')
    basic_dcm.report_fit()

    # hard to test things exactly because there's some randomness
    # involved, but can at least do a smoke test.
    assert len(loglik) == 3
    assert len(basic_dcm.fit_parameters) == 2
    assert len(basic_dcm.fit_parameters.columns) == 3

    repeated_index = alternatives.index.repeat([1, 2, 3, 2, 4, 3, 2, 1, 5, 8])
    repeated_alts = alternatives.loc[repeated_index].reset_index()

    choices = basic_dcm.predict(choosers, repeated_alts)

    pdt.assert_index_equal(choices.index, pd.Index([0, 1, 3, 4]))
    assert choices.isin(repeated_alts.index).all()


def test_mnl_dcm_yaml(basic_dcm, choosers, alternatives):
    expected_dict = {
        'model_type': 'discretechoice',
        'model_expression': basic_dcm.model_expression,
        'sample_size': basic_dcm.sample_size,
        'name': basic_dcm.name,
        'probability_mode': basic_dcm.probability_mode,
        'choice_mode': basic_dcm.choice_mode,
        'choosers_fit_filters': basic_dcm.choosers_fit_filters,
        'choosers_predict_filters': basic_dcm.choosers_predict_filters,
        'alts_fit_filters': basic_dcm.alts_fit_filters,
        'alts_predict_filters': basic_dcm.alts_predict_filters,
        'interaction_predict_filters': basic_dcm.interaction_predict_filters,
        'estimation_sample_size': basic_dcm.estimation_sample_size,
        'choice_column': basic_dcm.choice_column,
        'fitted': False,
        'log_likelihoods': None,
        'fit_parameters': None
    }

    assert yaml.load(basic_dcm.to_yaml()) == expected_dict

    new_mod = dcm.MNLDiscreteChoiceModel.from_yaml(basic_dcm.to_yaml())
    assert yaml.load(new_mod.to_yaml()) == expected_dict

    basic_dcm.fit(choosers, alternatives, 'thing_id')

    expected_dict['fitted'] = True
    del expected_dict['log_likelihoods']
    del expected_dict['fit_parameters']

    actual_dict = yaml.load(basic_dcm.to_yaml())
    assert isinstance(actual_dict.pop('log_likelihoods'), dict)
    assert isinstance(actual_dict.pop('fit_parameters'), dict)

    assert actual_dict == expected_dict

    new_mod = dcm.MNLDiscreteChoiceModel.from_yaml(basic_dcm.to_yaml())
    assert new_mod.fitted is True


def test_mnl_dcm_prob_mode_single(seed, basic_dcm_fit, choosers, alternatives):
    basic_dcm_fit.probability_mode = 'single_chooser'

    filtered_choosers, filtered_alts = basic_dcm_fit.apply_predict_filters(
        choosers, alternatives)

    probs = basic_dcm_fit.probabilities(choosers.iloc[1:], alternatives)

    pdt.assert_series_equal(
        probs,
        pd.Series(
            [0.25666709612190147,
             0.20225620916965448,
             0.15937989234214262,
             0.1255929308043417,
             0.077988133629030815,
             0.061455420294827229,
             0.04842747874412457,
             0.038161332007195688,
             0.030071506886781514],
            index=pd.MultiIndex.from_product(
                [[1], filtered_alts.index.values],
                names=['chooser_ids', 'alternative_ids'])))

    sprobs = basic_dcm_fit.summed_probabilities(choosers, alternatives)
    npt.assert_allclose(sprobs.sum(), len(filtered_choosers))


def test_mnl_dcm_choice_mode_agg(seed, basic_dcm_fit, choosers, alternatives):
    basic_dcm_fit.probability_mode = 'single_chooser'
    basic_dcm_fit.choice_mode = 'aggregate'

    filtered_choosers, filtered_alts = basic_dcm_fit.apply_predict_filters(
        choosers, alternatives)

    choices = basic_dcm_fit.predict(choosers, alternatives)

    pdt.assert_series_equal(
        choices,
        pd.Series(['f', 'a', 'd', 'c'], index=[0, 1, 3, 4]))


def test_mnl_dcm_group(seed, grouped_choosers, alternatives):
    model_exp = 'var2 + var1:var3'
    sample_size = 4
    choosers_predict_filters = ['var1 != 7']
    alts_predict_filters = ['var2 != 14']

    group = dcm.MNLDiscreteChoiceModelGroup('group')
    group.add_model_from_params(
        'x', model_exp, sample_size,
        choosers_predict_filters=choosers_predict_filters)
    group.add_model_from_params(
        'y', model_exp, sample_size, alts_predict_filters=alts_predict_filters)

    assert group.choosers_columns_used() == ['var1']
    assert group.alts_columns_used() == ['var2']
    assert set(group.interaction_columns_used()) == {'var1', 'var2', 'var3'}
    assert set(group.columns_used()) == {'var1', 'var2', 'var3'}

    assert group.fitted is False
    logliks = group.fit(grouped_choosers, alternatives, 'thing_id')
    assert group.fitted is True

    assert 'x' in logliks and 'y' in logliks
    assert isinstance(logliks['x'], dict) and isinstance(logliks['y'], dict)

    probs = group.probabilities(grouped_choosers, alternatives)
    for name, df in grouped_choosers.groupby('group'):
        assert name in probs
        filtered_choosers, filtered_alts = \
            group.models[name].apply_predict_filters(df, alternatives)
        assert len(probs[name]) == len(filtered_choosers) * len(filtered_alts)

    filtered_choosers, filtered_alts = group.apply_predict_filters(
        grouped_choosers, alternatives)

    sprobs = group.summed_probabilities(grouped_choosers, alternatives)
    assert len(sprobs) == len(filtered_alts)

    choice_state = np.random.get_state()
    choices = group.predict(grouped_choosers, alternatives)

    pdt.assert_series_equal(
        choices,
        pd.Series(['c', 'a', 'a', 'g'], index=[0, 3, 1, 4]))

    # check that we don't get the same alt twice if they are removed
    # make sure we're starting from the same random state as the last draw
    np.random.set_state(choice_state)
    group.remove_alts = True
    choices = group.predict(grouped_choosers, alternatives)

    pdt.assert_series_equal(
        choices,
        pd.Series(['c', 'a', 'b', 'g'], index=[0, 3, 1, 4]))


def test_mnl_dcm_segmented_raises():
    group = dcm.SegmentedMNLDiscreteChoiceModel('group', 2)

    with pytest.raises(ValueError):
        group.add_segment('x')


def test_mnl_dcm_segmented(seed, grouped_choosers, alternatives):
    model_exp = 'var2 + var1:var3'
    sample_size = 4

    group = dcm.SegmentedMNLDiscreteChoiceModel(
        'group', sample_size, default_model_expr=model_exp)
    group.add_segment('x')
    group.add_segment('y', 'var3 + var1:var2')

    assert group.choosers_columns_used() == []
    assert group.alts_columns_used() == []
    assert set(group.interaction_columns_used()) == {'var1', 'var2', 'var3'}
    assert set(group.columns_used()) == {'group', 'var1', 'var2', 'var3'}

    assert group.fitted is False
    logliks = group.fit(grouped_choosers, alternatives, 'thing_id')
    assert group.fitted is True

    assert 'x' in logliks and 'y' in logliks
    assert isinstance(logliks['x'], dict) and isinstance(logliks['y'], dict)

    probs = group.probabilities(grouped_choosers, alternatives)
    for name, df in grouped_choosers.groupby('group'):
        assert name in probs
        assert len(probs[name]) == len(df) * len(alternatives)

    sprobs = group.summed_probabilities(grouped_choosers, alternatives)
    assert len(sprobs) == len(alternatives)

    choice_state = np.random.get_state()
    choices = group.predict(grouped_choosers, alternatives)

    pdt.assert_series_equal(
        choices,
        pd.Series(['c', 'a', 'b', 'a', 'j'], index=[0, 2, 3, 1, 4]))

    # check that we don't get the same alt twice if they are removed
    # make sure we're starting from the same random state as the last draw
    np.random.set_state(choice_state)
    group._group.remove_alts = True
    choices = group.predict(grouped_choosers, alternatives)

    pdt.assert_series_equal(
        choices,
        pd.Series(['c', 'a', 'b', 'd', 'j'], index=[0, 2, 3, 1, 4]))


def test_mnl_dcm_segmented_yaml(grouped_choosers, alternatives):
    model_exp = 'var2 + var1:var3'
    sample_size = 4

    group = dcm.SegmentedMNLDiscreteChoiceModel(
        'group', sample_size, default_model_expr=model_exp, name='test_seg')
    group.add_segment('x')
    group.add_segment('y', 'var3 + var1:var2')

    expected_dict = {
        'model_type': 'segmented_discretechoice',
        'name': 'test_seg',
        'segmentation_col': 'group',
        'sample_size': sample_size,
        'probability_mode': 'full_product',
        'choice_mode': 'individual',
        'choosers_fit_filters': None,
        'choosers_predict_filters': None,
        'alts_fit_filters': None,
        'alts_predict_filters': None,
        'interaction_predict_filters': None,
        'estimation_sample_size': None,
        'choice_column': None,
        'default_config': {
            'model_expression': model_exp,
        },
        'remove_alts': False,
        'fitted': False,
        'models': {
            'x': {
                'name': 'x',
                'fitted': False,
                'log_likelihoods': None,
                'fit_parameters': None
            },
            'y': {
                'name': 'y',
                'model_expression': 'var3 + var1:var2',
                'fitted': False,
                'log_likelihoods': None,
                'fit_parameters': None
            }
        }
    }

    assert yaml.load(group.to_yaml()) == expected_dict

    new_seg = dcm.SegmentedMNLDiscreteChoiceModel.from_yaml(group.to_yaml())
    assert yaml.load(new_seg.to_yaml()) == expected_dict

    group.fit(grouped_choosers, alternatives, 'thing_id')

    expected_dict['fitted'] = True
    expected_dict['models']['x']['fitted'] = True
    expected_dict['models']['y']['fitted'] = True
    del expected_dict['models']['x']['fit_parameters']
    del expected_dict['models']['x']['log_likelihoods']
    del expected_dict['models']['y']['fit_parameters']
    del expected_dict['models']['y']['log_likelihoods']

    actual_dict = yaml.load(group.to_yaml())
    assert isinstance(actual_dict['models']['x'].pop('fit_parameters'), dict)
    assert isinstance(actual_dict['models']['x'].pop('log_likelihoods'), dict)
    assert isinstance(actual_dict['models']['y'].pop('fit_parameters'), dict)
    assert isinstance(actual_dict['models']['y'].pop('log_likelihoods'), dict)

    assert actual_dict == expected_dict

    new_seg = dcm.SegmentedMNLDiscreteChoiceModel.from_yaml(group.to_yaml())
    assert new_seg.fitted is True


def test_segmented_dcm_removes_old_models(grouped_choosers, alternatives):
    model_exp = 'var2 + var1:var3'
    sample_size = 4

    group = dcm.SegmentedMNLDiscreteChoiceModel(
        'group', sample_size, default_model_expr=model_exp)
    group.add_segment('a')
    group.add_segment('b')
    group.add_segment('c')

    group.fit(grouped_choosers, alternatives, 'thing_id')

    assert sorted(group._group.models.keys()) == ['x', 'y']


def test_fit_from_cfg(basic_dcm, choosers, alternatives):
    cfgname = tempfile.NamedTemporaryFile(suffix='.yaml').name
    basic_dcm.to_yaml(cfgname)
    dcm.MNLDiscreteChoiceModel.fit_from_cfg(
        choosers, "thing_id", alternatives, cfgname)
    dcm.MNLDiscreteChoiceModel.predict_from_cfg(
        choosers, alternatives, cfgname)

    dcm.MNLDiscreteChoiceModel.predict_from_cfg(choosers, alternatives,
                                                cfgname, .2)
    os.remove(cfgname)


def test_fit_from_cfg_segmented(grouped_choosers, alternatives):
    model_exp = 'var2 + var1:var3'
    sample_size = 4

    group = dcm.SegmentedMNLDiscreteChoiceModel(
        'group', sample_size, default_model_expr=model_exp)
    group.add_segment('x')
    group.add_segment('y', 'var3 + var1:var2')

    cfgname = tempfile.NamedTemporaryFile(suffix='.yaml').name
    group.to_yaml(cfgname)
    dcm.SegmentedMNLDiscreteChoiceModel.fit_from_cfg(grouped_choosers,
                                                     "thing_id",
                                                     alternatives,
                                                     cfgname)
    dcm.SegmentedMNLDiscreteChoiceModel.predict_from_cfg(grouped_choosers,
                                                         alternatives,
                                                         cfgname)

    dcm.SegmentedMNLDiscreteChoiceModel.predict_from_cfg(grouped_choosers,
                                                         alternatives,
                                                         cfgname,
                                                         .8)
    os.remove(cfgname)
