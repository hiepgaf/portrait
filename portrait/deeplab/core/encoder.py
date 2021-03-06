"""Implementation of DeepLabV3+ - A deep atrous separable 
convolution neural network. (so wordy!!!)

For object segmentation task:
  * Output stride (input / output res. ratio)  = 16 (or 8) 
  for denser feature extraction.
  * Atrous Conv Rate = 2 , or 4 to the last two blocks/
  (for output stride = 8).
  * Atrous Spatial Pyramid Pooling : https://arxiv.org/pdf/1706.05587.pdf
  (Feature_Map) --> (Global Pooling) ---> (1 x 1) Conv, 256 filters
  ---> (Batch Normalization) --> Atrous Conv Rates =(12, 24, 36)
  ---> Output stride = 8 (reduce atrous rate by factor of two if output_stride=16)

# TODO:
   * Add suggested hyperparameters for training
   * Removed fixed image size
"""
import tensorflow as tf

from portrait.deeplab.core import ops
from portrait.deeplab.core.feature_extractor import feature_extractor


def extract_features(images,
                     is_training=True,
                     network_backbone='mobilenet_v2', 
                     output_stride=8):
  """Extract sematic  features, given a network
  backbone (e.g. MobileNetv2, Xception). Then, perform
  "atrous spatial pyramid pooling" to get a concatenated 
  encoded features.

  Args:
    images:
    is_training:
    network_backbone:
    output_stride:
  
  Returns:
    encoded_features - 4D Tensor
    low_level_features - 4D Tensor
    
  Raise:
    ValueError: `output_stride` or `network_backbone` input
      is invalid.
  """
  if output_stride not in {8, 16}:
    raise ValueError(
      "`output_stride` should be 8, 16, or 32.")  

  if network_backbone not in ['mobilenet_v2', 'xception']:
    raise ValueError(
        "`network_backbone` should be 'mobilenet_v2' or 'xception'")

  # Extract feature map and low level features
  # from network backbone.
  feature_map, low_level_features = feature_extractor(
      images=images,
      model_variant=network_backbone,
      is_training=is_training)

  assp_features = atrous_spatial_pyramid_pooling(
      network_backbone,
      feature_map,
      depth=256,
      output_stride=8)

  # Merge all atrous features into a feature map
  features = tf.layers.Conv2D(256, (1, 1))(assp_features)
  features = tf.layers.batch_normalization(features)
  features = tf.nn.relu6(features)

  return features, low_level_features


def atrous_spatial_pyramid_pooling(network_backbone,
                                   feature_map,
                                   depth=256,
                                   normalizer_fn=tf.layers.BatchNormalization,
                                   activation_fn=tf.nn.relu6,
                                   output_stride=8,
                                   ):
  """

  Args:
    network_backbone:
    feature_map:
    depth:
    normalizer_fn:
    activation_fn:
    output_stride:

  Returns:

  """
  atrous_rates = [12, 24, 36] if output_stride == 8 else [6, 12, 18]
  with tf.variable_scope(name_or_scope='aspp'):
    logit_branches = []
    pool_height = scale_dimension(224, 1. / output_stride)
    pool_width = scale_dimension(224, 1. / output_stride)

    # Image feature level
    with tf.variable_scope('image_level_pooling'):
      image_feature = tf.layers.AveragePooling2D(
          pool_size=(pool_height, pool_width),
          strides=2)(feature_map)
      image_feature = tf.layers.Conv2D(depth, (1, 1))(image_feature)
      image_feature = tf.image.resize_bilinear(
          images=image_feature,
          size=[pool_height, pool_width],
          align_corners=True)
      image_feature.set_shape([None, pool_height, pool_width, depth])
      logit_branches.append(image_feature)

    # 1x1 Conv
    with tf.variable_scope('1x1_conv_pooling'):
      conv_1x1 = tf.layers.Conv2D(depth, (1, 1))(feature_map)
      logit_branches.append(conv_1x1)

    # 3x3 Atrous Separable Convs,
    if network_backbone != 'mobilenet_v2':
      for idx, rate in enumerate(atrous_rates):
        scope = 'aspp_%s' % idx
        assp_features = _atrous_separable_conv(
            features=feature_map,
            output_depth=depth,
            kernel_size=3,
            atrous_rate=rate,
            activation_fn=activation_fn,
            normalizer_fn=normalizer_fn,
            scope=scope)
        logit_branches.append(assp_features)

    return tf.concat(logit_branches, 3)


def _atrous_separable_conv(features, 
                           output_depth,
                           kernel_size=3,
                           strides=1,
                           atrous_rate=1, 
                           activation_fn=tf.nn.relu6,
                           normalizer_fn=tf.nn.batch_normalization,
                           scope=None):
  """
  
  Args:
    features: 
    output_depth: 
    kernel_size: 
    strides: 
    atrous_rate: 
    weight_decay: 
    activation_fn: 
    normalizer_fn: 
    scope: 

  Returns:

  """"""
  @TODO: add weight_decay, weight_regularizer, scope
  """
  with tf.variable_scope(scope):
    if strides == 1:
      padding = 'same'
    else:
      padding = 'valid'
      kernel_size_effective = kernel_size + (kernel_size - 1) * (atrous_rate - 1)
      features = ops.pad_inputs(features, kernel_size_effective)

    depthwise_conv = tf.keras.layers.DepthwiseConv2D(
        kernel_size=(3, 3),
        strides=strides,
        depth_multiplier=1,
        dilation_rate=(atrous_rate, atrous_rate),
        padding=padding)(features)
    depthwise_conv = normalizer_fn(depthwise_conv)
    depthwise_conv = activation_fn(depthwise_conv)

    pointwise_conv = tf.layers.Conv2D(
        filters=output_depth,
        kernel_size=(1, 1),
        padding='SAME')(depthwise_conv)
    pointwise_conv = normalizer_fn(pointwise_conv)
    pointwise_conv = activation_fn(pointwise_conv)
  return pointwise_conv


def scale_dimension(dim, scale):
  """Scales the input dimension.

  Args:
    dim: Input dimension (a scalar or a scalar Tensor).
    scale: The amount of scaling applied to the input.

  Returns:
    Scaled dimension.
  """
  if isinstance(dim, tf.Tensor):
    return tf.cast((tf.to_float(dim) - 1.0) * scale + 1.0, dtype=tf.int32)
  else:
    return int((float(dim) - 1.0) * scale + 1.0)