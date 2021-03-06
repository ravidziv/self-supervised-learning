"""Models for SSL."""
import tensorflow as tf

import self_supervised.models.resent_model as resnet


class LinearLayer(tf.keras.layers.Layer):

    def __init__(self,
                 num_classes,
                 use_bias: bool = True,
                 use_bn: bool = False,
                 name: str = 'linear_layer',
                 **kwargs):
        """

        :param num_classes:
        :param use_bias:
        :param use_bn:
        :param name:
        :param kwargs:
        """
        # Note: use_bias is ignored for the dense layer when use_bn=True.
        # However, it is still used for batch norm.
        super(LinearLayer, self).__init__(**kwargs)
        self.num_classes = num_classes
        self.use_bias = use_bias
        self.use_bn = use_bn
        self._name = name
        if self.use_bn:
            self.bn_relu = resnet.BatchNormRelu(relu=False, center=use_bias)
        self.dense = None

    def build(self, input_shape):
        if callable(self.num_classes):
            num_classes = self.num_classes(input_shape)
        else:
            num_classes = self.num_classes
        self.dense = tf.keras.layers.Dense(
            num_classes,
            kernel_initializer=tf.keras.initializers.RandomNormal(stddev=0.01),
            use_bias=self.use_bias and not self.use_bn)
        super(LinearLayer, self).build(input_shape)

    def call(self, inputs, training=None, **kwargs):
        assert inputs.shape.ndims == 2, inputs.shape
        inputs = self.dense(inputs)
        if self.use_bn:
            inputs = self.bn_relu(inputs, training=training)
        return inputs


class ProjectionHead(tf.keras.layers.Layer):

    def __init__(self, proj_out_dim: int, proj_head_mode: str, num_proj_layers: int, ft_proj_selector: int, **kwargs):
        """
        Model for the projection head of the SimCLR
        :param proj_out_dim:
        :param proj_head_mode:
        :param num_proj_layers:
        :param ft_proj_selector:
        :param kwargs:
        """
        self.linear_layers = []
        self.proj_head_mode = proj_head_mode
        self.num_proj_layers = num_proj_layers
        self.ft_proj_selector = ft_proj_selector
        if self.proj_head_mode == 'none':
            pass  # directly use the output hiddens as hiddens
        elif self.proj_head_mode == 'linear':
            self.linear_layers = [
                LinearLayer(
                    num_classes=proj_out_dim, use_bias=False, use_bn=True, name='l_0')
            ]
        elif self.proj_head_mode == 'nonlinear':
            for j in range(num_proj_layers):
                if j != num_proj_layers - 1:
                    # for the middle layers, use bias and relu for the output.
                    self.linear_layers.append(
                        LinearLayer(
                            num_classes=lambda input_shape: int(input_shape[-1]),
                            use_bias=True,
                            use_bn=True,
                            name='nl_%d' % j))
                else:
                    # for the final layer, neither bias nor relu is used.
                    self.linear_layers.append(
                        LinearLayer(
                            num_classes=proj_out_dim,
                            use_bias=False,
                            use_bn=True,
                            name='nl_%d' % j))
        else:
            raise ValueError('Unknown head projection mode {}'.format(
                self.proj_head_mode))
        super(ProjectionHead, self).__init__(**kwargs)

    def call(self, inputs, training=None, **kwargs):
        if self.proj_head_mode == 'none':
            return inputs  # directly use the output hiddens as hiddens
        hiddens_list = [tf.identity(inputs, 'proj_head_input')]
        if self.proj_head_mode == 'linear':
            assert len(self.linear_layers) == 1, len(self.linear_layers)
            return hiddens_list.append(self.linear_layers[0](hiddens_list[-1],
                                                             training))
        elif self.proj_head_mode == 'nonlinear':
            for j in range(self.num_proj_layers):
                hiddens = self.linear_layers[j](hiddens_list[-1], training)
                if j != self.num_proj_layers - 1:
                    # for the middle layers, use bias and relu for the output.
                    hiddens = tf.nn.relu(hiddens)
                hiddens_list.append(hiddens)
        else:
            raise ValueError('Unknown head projection mode {}'.format(
                self.proj_head_mode))
        # The first element is the output of the projection head.
        # The second element is the input of the finetune head.
        proj_head_output = tf.identity(hiddens_list[-1], 'proj_head_output')
        return proj_head_output, hiddens_list[self.ft_proj_selector]


class SupervisedHead(tf.keras.layers.Layer):

    def __init__(self, num_classes: int, name: str = 'head_supervised', **kwargs):
        """
        Model for the supervised head
        :param num_classes:
        :param name:
        """
        super(SupervisedHead, self).__init__(name=name, **kwargs)
        self.linear_layer = LinearLayer(num_classes)

    def call(self, inputs, training=None, **kwargs):
        inputs = self.linear_layer(inputs, training)
        inputs = tf.identity(inputs, name='logits_sup')
        return inputs
