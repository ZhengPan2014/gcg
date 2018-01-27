import tensorflow as tf

from gcg.policies.tf import rnn_cell
from gcg.policies.tf.bnn.concrete_dropout import ConcreteDropout
from gcg.policies.tf.bnn.bayes_by_backprop import BayesByBackprop
from gcg.policies.tf.bnn.probabilistic_backprop import PBP_net
from gcg.policies.tf.bnn.bootstrap.bootstrap import Bootstrap

def convnn(
        inputs,
        params,
        scope='convnn',
        dtype=tf.float32,
        data_format='NHWC',
        reuse=False,
        is_training=True,
        global_step_tensor=None):
    if params['conv_activation'] == 'relu':
        conv_activation = tf.nn.relu
    else:
        raise NotImplementedError(
            'Conv activation {0} is not valid'.format(
                params['conv_activation']))

    if 'output_activation' not in params:
        output_activation = None
    elif params['output_activation'] == 'sigmoid':
        output_activation = tf.nn.sigmoid
    elif params['output_activation'] == 'softmax':
        output_activation = tf.nn.softmax
    elif params['output_activation'] == 'tanh':
        output_activation = tf.nn.tanh
    elif params['output_activation'] == 'relu':
        output_activation = tf.nn.relu
    else:
        raise NotImplementedError(
            'Output activation {0} is not valid'.format(
                params['output_activation']))

    kernels = params['kernels']
    filters = params['filters']
    strides = params['strides']
    # Assuming all paddings will be the same type
    padding = params['padding']
    normalizer = params.get('normalizer', None)
    trainable = params.get('trainable', True)
    next_layer_input = inputs
    with tf.variable_scope(scope, reuse=reuse):
        for i in range(len(kernels)):
            if i == len(kernels) - 1:
                activation = output_activation
            else:
                activation = conv_activation
            if normalizer == 'batch_norm':
                normalizer_fn = tf.contrib.layers.batch_norm
                normalizer_params = {
                    'is_training': is_training,
                    'data_format': data_format,
                    'fused': True,
                    'decay': params.get('batch_norm_decay', 0.999),
                    'zero_debias_moving_mean': True,
                    'scale': True,
                    'center': True,
                    'updates_collections': None
                }
            elif normalizer == 'layer_norm':
                normalizer_fn = tf.contrib.layers.layer_norm
                normalizer_params = {
                    'scale': True,
                    'center': True
                }
            elif normalizer is None:
                normalizer_fn = None
                normalizer_params = None
            else:
                raise NotImplementedError(
                    'Normalizer {0} is not valid'.format(normalizer))

            next_layer_input = tf.contrib.layers.conv2d(
                inputs=next_layer_input,
                num_outputs=filters[i],
                data_format=data_format,
                kernel_size=kernels[i],
                stride=strides[i],
                padding=padding,
                activation_fn=activation,
                normalizer_fn=normalizer_fn,
                normalizer_params=normalizer_params,
                weights_initializer=tf.contrib.layers.xavier_initializer_conv2d(dtype=dtype),
                weights_regularizer=tf.contrib.layers.l2_regularizer(0.5),
                biases_initializer=tf.constant_initializer(0., dtype=dtype),
                trainable=trainable)

    output = next_layer_input
    # TODO
    return output, None


def fcnn(
        inputs,
        params,
        dp_masks=None,
        num_dp=1,
        dtype=tf.float32,
        data_format='NCHW',
        scope='fcnn',
        reuse=False,
        is_training=True,
        T=None,
        global_step_tensor=None):
    if 'hidden_activation' not in params:
        hidden_activation = None
    elif params['hidden_activation'] == 'relu':
        hidden_activation = tf.nn.relu
    elif params['hidden_activation'] == 'tanh':
        hidden_activation = tf.nn.tanh
    else:
        raise NotImplementedError(
            'Hidden activation {0} is not valid'.format(
                params['hidden_activation']))

    if 'output_activation' not in params or params['output_activation'] == 'None':
        output_activation = None
    elif params['output_activation'] == 'sigmoid':
        output_activation = tf.nn.sigmoid
    elif params['output_activation'] == 'softmax':
        output_activation = tf.nn.softmax
    elif params['output_activation'] == 'relu':
        output_activation = tf.nn.relu
    elif params['output_activation'] == 'tanh':
        output_activation = tf.nn.tanh
    else:
        raise NotImplementedError(
            'Output activation {0} is not valid'.format(
                params['output_activation']))

    hidden_layers = params.get('hidden_layers', [])
    output_dim = params['output_dim']
    dropout = params.get('dropout', None)
    bnn_method = params.get('bnn_method', None)
    if bnn_method == 'concrete_dropout' and dropout is None:
        dropout = 0.1  # rowan's overriding hack (note: specific value not used)
    normalizer = params.get('normalizer', None)
    assert(normalizer is None)
    if dp_masks is not None or dropout is None:
        dp_return_masks = None
    else:
        dp_return_masks = []
        distribution = tf.contrib.distributions.Uniform()

    dims = hidden_layers + [output_dim]

    if T is None:
        assert(len(inputs.get_shape()) == 2)
        next_layer_input = inputs
    else:
        assert(len(inputs.get_shape()) == 3)
        assert(inputs.get_shape()[1].value == T)
        next_layer_input = tf.reshape(inputs, (-1, inputs.get_shape()[-1].value))

    trainable = params.get('trainable', True)

    with tf.variable_scope(scope, reuse=reuse):
        for i, dim in enumerate(dims):
            with tf.variable_scope('l{0}'.format(i)):
                if i == len(dims) - 1:
                    activation = output_activation
                else:
                    activation = hidden_activation

                num_data = params.get('num_data', None)  # TODO: find a better solution than yaml file to get this value
                batch_size = params.get('batch_size', None)  # TODO: find a better solution than yaml file to get this value
                bnn_layer_name = "bnn_{}_{}".format(bnn_method, i)
                if bnn_method == 'concrete_dropout':
                    input_dim = next_layer_input.get_shape()[1].value
                    concrete_dropout = ConcreteDropout(bnn_layer_name, num_data, input_dim)
                    fc_layer = tf.contrib.layers.fully_connected
                    weight_regularizer_scale = concrete_dropout.get_weight_regularizer_scale()
                elif bnn_method == 'bayes_by_backprop':
                    bayes_by_backprop = BayesByBackprop(bnn_layer_name, num_data, batch_size)
                    # note: object is callable like a layer, but only assumes a one-time call per instance
                    fc_layer = bayes_by_backprop
                    weight_regularizer_scale = bayes_by_backprop.get_weight_regularizer_scale()
                elif bnn_method == 'probabilistic_backprop':
                    probabilistic_backprop = PBP_net.PBP_net()  # TODO: can this handle being layer-wise?
                    fc_layer = probabilistic_backprop
                    weight_regularizer_scale = 0.0
                elif bnn_method == 'bootstrap':
                    fc_layer = Bootstrap(params['num_bootstraps'])
                    weight_regularizer_scale = 0.5
                elif bnn_method is not None:
                    raise NotImplementedError(bnn_method)
                else:
                    fc_layer = tf.contrib.layers.fully_connected
                    weight_regularizer_scale = 0.5

                next_layer_input = fc_layer(
                    inputs=next_layer_input,
                    num_outputs=dim,
                    activation_fn=activation,
                    normalizer_fn=None,
                    normalizer_params=None,
                    weights_initializer=tf.contrib.layers.xavier_initializer(dtype=dtype),
                    biases_initializer=tf.constant_initializer(0., dtype=dtype),
                    weights_regularizer=tf.contrib.layers.l2_regularizer(weight_regularizer_scale),
                    trainable=trainable)

                if dropout is not None:
                    assert (type(dropout) is float and 0 < dropout and dropout <= 1.0)
                    if dp_masks is not None:
                        next_layer_input = next_layer_input * dp_masks[i]
                    else:
                        # Shape is not well defined without reshaping
                        shape = tf.shape(next_layer_input)
                        if num_dp > 1:
                            sample = distribution.sample(tf.stack((shape[0] // num_dp, dim)))
                            sample = tf.concat([sample] * num_dp, axis=0)
                        else:
                            sample = distribution.sample(shape)
                        sample = tf.reshape(sample, (-1, dim))
                        if bnn_method == 'concrete_dropout':
                            next_layer_input, mask = concrete_dropout.apply_soft_dropout_mask(next_layer_input, sample)
                        else:
                            mask = tf.cast(sample < dropout, dtype) / dropout
                            next_layer_input = next_layer_input * mask
                        dp_return_masks.append(mask)

        output = next_layer_input

        if T is not None:
            output = tf.reshape(output, (-1, T, output.get_shape()[-1].value))

    return output, dp_return_masks



def rnn(
        inputs,
        params,
        initial_state=None,
        dp_masks=None,
        num_dp=1,
        dtype=tf.float32,
        scope='rnn',
        reuse=False):
    """
    inputs is shape [batch_size x T x features].
    """
    num_cells = params['num_cells']
    cell_args = params.get('cell_args', {})
    if params['cell_type'] == 'rnn':
        cell_type = rnn_cell.DpRNNCell
        if initial_state is not None:
            initial_state = tf.split(initial_state, num_cells, axis=1)
            num_units = initial_state[0].get_shape()[1].value
    elif params['cell_type'] == 'mulint_rnn':
        cell_type = rnn_cell.DpMulintRNNCell
        if initial_state is not None:
            initial_state = tuple(tf.split(initial_state, num_cells, axis=1))
            num_units = initial_state[0].get_shape()[1].value
    elif params['cell_type'] == 'lstm':
        assert ('use_layer_norm' not in cell_args)

        cell_type = rnn_cell.DpLSTMCell
        cell_args = dict([(k, v) for k, v in cell_args.items() if k != 'use_layer_norm'])
        if initial_state is not None:
            states = tf.split(initial_state, 2 * num_cells, axis=1)
            num_units = states[0].get_shape()[1].value
            initial_state = []
            for i in range(num_cells):
                initial_state.append(tf.nn.rnn_cell.LSTMStateTuple(states[i * 2], states[i * 2 + 1]))
            initial_state = tuple(initial_state)
    elif params['cell_type'] == 'mulint_lstm':
        cell_type = rnn_cell.DpMulintLSTMCell
        if initial_state is not None:
            states = tf.split(initial_state, 2 * num_cells, axis=1)
            num_units = states[0].get_shape()[1].value
            initial_state = []
            for i in range(num_cells):
                initial_state.append(tf.nn.rnn_cell.LSTMStateTuple(states[i * 2], states[i * 2 + 1]))
            initial_state = tuple(initial_state)
    else:
        raise NotImplementedError(
            'Cell type {0} is not valid'.format(params['cell_type']))

    if initial_state is None:
        num_units = params['num_units']
    dropout = params.get('dropout', None)
    if dp_masks is not None or dropout is None:
        dp_return_masks = None
    else:
        dp_return_masks = []
        distribution = tf.contrib.distributions.Uniform()
    cells = []

    with tf.variable_scope(scope, reuse=reuse):
        for i in range(num_cells):
            if dropout is not None:
                assert (type(dropout) is float and 0 < dropout and dropout <= 1.0)
                if dp_masks is not None:
                    dp = dp_masks[i]
                else:
                    if num_dp > 1:
                        sample = distribution.sample(tf.stack((tf.shape(inputs)[0] // num_dp, num_units)))
                        sample = tf.concat([sample] * num_dp, axis=0)
                    else:
                        sample = distribution.sample((tf.shape(inputs)[0], num_units))
                    # Shape is not well defined without reshaping
                    sample = tf.reshape(sample, (-1, num_units))
                    mask = tf.cast(sample < dropout, dtype) / dropout
                    dp = mask
                    dp_return_masks.append(mask)
            else:
                dp = None

            if i == 0:
                num_inputs = inputs.get_shape()[-1]
            else:
                num_inputs = num_units
            if cell_type == tf.contrib.rnn.LayerNormBasicLSTMCell:
                cell = cell_type(num_units, **cell_args)
            else:
                cell = cell_type(
                    num_units,
                    dropout_mask=dp,
                    dtype=dtype,
                    num_inputs=num_inputs,
                    weights_scope='{0}_{1}'.format(params['cell_type'], i),
                    **cell_args)

            cells.append(cell)

        multi_cell = tf.nn.rnn_cell.MultiRNNCell(cells)
        outputs, state = tf.nn.dynamic_rnn(
            multi_cell,
            tf.cast(inputs, dtype),
            initial_state=initial_state,
            dtype=dtype,
            time_major=False)

    return outputs, dp_return_masks